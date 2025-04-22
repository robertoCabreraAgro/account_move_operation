from ast import literal_eval

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountMoveInvoiceTemplateRun(models.TransientModel):
    _name = "account.invoice.template.run"
    _description = "Wizard to generate invoice from template"
    _check_company_auto = True

    template_id = fields.Many2one(
        "account.move.template",
        required=True,
        check_company=True,
        domain="[('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one("account.journal", "Journal", readonly=True)
    move_type = fields.Selection(
        selection=[
            ("entry", "Journal Entry"),
            ("out_invoice", "Customer Invoice"),
            ("out_refund", "Customer Credit Note"),
            ("in_invoice", "Vendor Bill"),
            ("in_refund", "Vendor Credit Note"),
            ("out_receipt", "Sales Receipt"),
            ("in_receipt", "Purchase Receipt"),
        ],
        string="Type",
        default="entry",
    )
    company_currency_id = fields.Many2one(
        string="Company Currency",
        related="company_id.currency_id",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        "Currency",
    )
    partner_id = fields.Many2one(
        "res.partner",
        "Override Partner",
        domain=["|", ("parent_id", "=", False), ("is_company", "=", True)],
    )
    state = fields.Selection(
        selection=[("select_template", "Select Template"), ("set_lines", "Set Lines")],
        default="select_template",
        readonly=True,
    )
    ref = fields.Char("Reference")
    overwrite = fields.Text(
        help="""
            Valid dictionary to overwrite template lines:
            {
                "L1": {"partner_id": 1, "amount": 100, "name": "some label"},
                "L2": {"partner_id": 2, "amount": 200, "name": "some label 2"},
            }
        """
    )
    line_ids = fields.One2many("account.invoice.template.line.run", "wizard_id", "Lines")
    post = fields.Boolean(help="Set true if want to post the entry as it is created.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("template_id"):
                template = self.env["account.move.template"].browse(vals.get("template_id"))
                if not vals.get("company_id") or vals.get("company_id") != template.company_id.id:
                    vals["company_id"] = template.company_id.id
        return super().create(vals_list)

    def _get_valid_keys(self):
        return ["partner_id", "amount", "name", "date_maturity"]

    def _get_overwrite_vals(self):
        """valid_dict = {
            'L1': {'partner_id': 1, 'amount': 10},
            'L2': {'partner_id': 2, 'amount': 20},
        }
        """
        self.ensure_one()
        valid_keys = self._get_valid_keys()
        overwrite_vals = self.overwrite or "{}"
        try:
            overwrite_vals = literal_eval(overwrite_vals)
            assert isinstance(overwrite_vals, dict)
        except (SyntaxError, ValueError, AssertionError) as err:
            raise ValidationError(_("Overwrite value must be a valid python dict")) from err
        # First level keys must be L1, L2, ...
        keys = overwrite_vals.keys()
        if list(filter(lambda x: x[:1] != "L" or not x[1:].isdigit(), keys)):
            raise ValidationError(_("Keys must be line sequence, i..e, L1, L2, ..."))
        # Second level keys must be a valid keys
        try:
            if dict(filter(lambda x: set(overwrite_vals[x].keys()) - set(valid_keys), keys)):
                raise ValidationError(_("Valid fields to overwrite are %s", valid_keys))
        except ValidationError as e:
            raise e
        except Exception as e:
            msg = """
                valid_dict = {
                    'L1': {'partner_id': 1, 'amount': 10},
                    'L2': {'partner_id': 2, 'amount': 20},
                }
            """
            raise ValidationError(
                _(
                    "Invalid dictionary: %(exception)s\n%(msg)s",
                    exception=e,
                    msg=msg,
                )
            ) from e
        return overwrite_vals

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if self.line_ids:
            self.line_ids.unlink()
        if self.template_id:
            self.update(self.template_id.prepare_wizard_values())
            amtlr_obj = self.env["account.invoice.template.line.run"]
            lines = self.env["account.invoice.template.line.run"]
            overwrite_vals = self._get_overwrite_vals()
            for tl in self.template_id.line_ids:
                vals = {"wizard_id": self.id}
                vals.update(tl._prepare_wizard_line_vals(overwrite_vals))
                lines |= amtlr_obj.create(vals)
            if self.env.context.get("amount"):
                lines[:1].amount = self.env.context.get("amount")

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            for line in self.line_ids:
                line.partner_id = self.partner_id

    def _validate_wizard_integrity(self):
        input_sequence2amount = self.template_id.line_ids_integrity.copy()
        k = self.template_id.line_ids_integrity.keys()
        for line in self.line_ids:
            if line.line_id.sequence not in k:
                raise UserError(
                    _(
                        "You deleted a line in the wizard. This is not allowed: "
                        "you should either update the template or modify the "
                        "journal entry that will be generated by this wizard."
                    )
                )
            input_sequence2amount.pop(line.line_id.sequence)
        if input_sequence2amount:
            raise UserError(
                _(
                    "You added a line in the wizard. This is not allowed: "
                    "you should either update the template or modify "
                    "the journal entry that will be generated by this wizard."
                )
            )

    def _validate_not_all_zero(self):
        if all(self.company_currency_id.is_zero(line.amount) for line in self.line_ids):
            raise UserError(_("Debit and credit of all lines are null."))

    def _prepare_move_vals(self):
        invoice_date_type = ("in_invoice", "in_refund", "out_invoice", "out_refund")
        invoice_date = self.date if self.move_type in invoice_date_type else False
        partner = self.partner_id.id if self.partner_id else False
        vals = {
            "company_id": self.company_id.id,
            "partner_id": partner,
            "date": self.date,
            "invoice_date": invoice_date,
            "journal_id": self.journal_id.id,
            "currency_id": self.currency_id.id,
            "move_type": self.move_type,
            "ref": self.ref,
            "line_ids": [],
        }
        return vals

    def action_open_move(self, move):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_journal_line")
        action.update(
            {
                "name": _("Entry from template %s", self.template_id.name),
                "res_id": move.id,
                "views": False,
                "view_id": False,
                "view_mode": "form,tree,kanban",
                "context": self.env.context,
            }
        )
        return action

    def generate_move(self):
        self.ensure_one()
        self._validate_wizard_integrity()
        for line in self.line_ids.filtered(lambda ln: ln.type == "computed"):
            line._compute_line()
        self._validate_not_all_zero()
        move_vals = self._prepare_move_vals()
        for line in self.line_ids.filtered(lambda ln: not ln.company_currency_id.is_zero(ln.amount)):
            move_vals["line_ids"].append(Command.create(line._prepare_move_line_vals()))
        move = self.env["account.move"].create(move_vals)
        if self.env.context.get("operation_line_id"):
            operation_line = self.env["account.move.operation.line"].browse(self.env.context.get("operation_line_id"))
            operation_line.move_id = move
            operation_line.action_in_progress()
        action = self.action_open_move(move)
        overwrite_vals = self._get_overwrite_vals()
        for key in overwrite_vals.keys():
            overwrite_vals[key].pop("amount", None)
        if self.post:
            move.action_post()
        action["context"] = dict(action.get("context", {}), overwrite=overwrite_vals)
        return action
