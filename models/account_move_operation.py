from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class AccountMoveOperation(models.Model):
    _name = "account.move.operation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Account Move Operations"
    _check_company_auto = True

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
        help="Leave this field empty if this route is shared between all companies",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id.id,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        domain=["|", ("parent_id", "=", False), ("is_company", "=", True)],
    )
    operation_type_id = fields.Many2one(
        comodel_name="account.move.operation.type",
        string="Type",
        required=True,
        domain="[('company_id', '=', company_id), ('sub_operation', '=', False)]",
        index=True,
    )
    st_line_id = fields.Many2one(
        comodel_name="account.bank.statement.line",
        string="Bank Statement Line",
        domain=["|", ("partner_id", "=", partner_id), ("partner_id", "=", False)],
    )
    name = fields.Char(
        string="Operation",
        required=True,
        default=lambda self: _("New"),
        readonly=True,
        copy=False,
        tracking=True,
        index="trigram",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancel", "Cancel"),
        ],
        default="draft",
        copy=False,
        readonly=True,
        tracking=True,
    )
    reference = fields.Char(copy=False)
    amount = fields.Monetary(currency_field="currency_id")
    from_bank_statement = fields.Boolean(related="operation_type_id.from_bank_statement")
    line_ids = fields.One2many("account.move.operation.line", "operation_id", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "company_id" in vals:
                self = self.sudo().with_company(vals["company_id"])
            if vals.get("name", _("New")) == _("New"):
                seq_date = (
                    fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(vals["date"]))
                    if "date" in vals
                    else None
                )
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "account.move.operation", sequence_date=seq_date
                ) or _("New")
        return super().create(vals_list)

    @api.onchange("st_line_id")
    def onchange_st_line(self):
        if self.st_line_id:
            self.update(
                {
                    "partner_id": self.st_line_id.partner_id.id or self.partner_id.id,
                    "currency_id": self.st_line_id.currency_id.id or self.currency_id.id,
                    "amount": self.st_line_id.amount,
                }
            )

    @api.onchange("partner_id")
    def onchange_partner(self):
        if self.st_line_id.partner_id and self.st_line_id.partner_id != self.partner_id:
            self.update(
                {
                    "st_line_id": False,
                }
            )

    def action_start(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Please set a partner before starting operation."))
        if self.state != "draft":
            return
        self._create_lines()
        self.state = "in_progress"

    def action_done(self):
        self.ensure_one()
        if self.state != "in_progress":
            return
        self.state = "done"

    def action_cancel(self):
        self.ensure_one()
        if self.state in ["done", "cancel"]:
            return
        self.state = "cancel"
        self.line_ids.action_cancel()

    def action_next_step(self):
        self.ensure_one()
        if self.state != "in_progress":
            return
        return self._get_next_action()

    def action_open_bank_statement_line(self):
        return self.st_line_id.action_open_recon_st_line()

    def _create_lines(self):
        line = self.env["account.move.operation.line"]
        vals_list = []
        for rule in self.operation_type_id.action_ids:
            vals_list.append(self._get_line_vals(rule))
        for vals in vals_list:
            if line:
                vals["orig_line_id"] = line.id
            else:
                vals["state"] = "ready"
            line = line.create(vals)

    def _get_line_vals(self, rule):
        vals = {
            "name": rule.name,
            "action": rule.action,
            "state": "waiting",
            "template_id": rule.template_id.id,
            "journal_id": rule.journal_id.id,
            "operation_id": self.id,
            "date_last_document": rule.date_last_document,
            "diff_partner": rule.diff_partner,
            "action_id": rule.id,
        }
        return vals

    def _get_next_action(self):
        in_progress_line = self.line_ids.filtered(lambda line: line.state == "in_progress")[:1]
        if in_progress_line:
            operation = in_progress_line.created_operation_id
            if operation and operation.company_id != self.env.company:
                raise UserError(
                    _(
                        "Please continue process on operation: %s in company %s",
                        operation.name,
                        operation.company_id.name,
                    )
                )
            return in_progress_line.action_open_document()
        nxt_line = self.line_ids.filtered(lambda line: line.state == "ready")
        if not nxt_line:
            raise UserError(_("There is no available action to execute."))
        context = self._context.copy()
        context.update(
            {
                "operation_id": self.id,
                "operation_line_id": nxt_line.id,
            }
        )
        return nxt_line.with_context(**context)._get_action()


class AccountMoveOperationLine(models.Model):
    _name = "account.move.operation.line"
    _description = "Account Move Operation Lines"

    operation_id = fields.Many2one(
        comodel_name="account.move.operation",
        required=True,
        readonly=True,
    )
    name = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        selection=[
            ("waiting", "Waiting"),
            ("ready", "Ready"),
            ("done", "Done"),
            ("cancel", "Cancel"),
            ("in_progress", "In Progress"),
            # ("waiting_operation", "Waiting another operation"),
        ],
        default="draft",
        copy=False,
        readonly=True,
    )
    orig_line_id = fields.Many2one(
        comodel_name="account.move.operation.line",
        readonly=True,
        compute="_compute_orig_line",
        inverse="_inverse_orig_line",
        store=True,
    )
    dest_line_id = fields.Many2one(
        comodel_name="account.move.operation.line",
        readonly=True,
        compute="_compute_dest_line",
        inverse="_inverse_dest_line",
        store=True,
    )
    action = fields.Selection(
        selection=[
            ("move", "Create Journal Entry"),
            ("pay", "Create Payment"),
            ("reconcile", "Reconcile Payment"),
            ("operation", "Create Operation"),
            ("info", "Information"),
        ],
        required=True,
        index=True,
    )
    template_id = fields.Many2one("account.move.template", "Move Template", readonly=True)
    journal_id = fields.Many2one("account.journal", "Journal", readonly=True)
    move_id = fields.Many2one("account.move", readonly=True)
    payment_id = fields.Many2one("account.payment", readonly=True)
    st_line_id = fields.Many2one("account.bank.statement.line", readonly=True)
    action_id = fields.Many2one("account.move.operation.action", readonly=True)
    created_operation_id = fields.Many2one("account.move.operation", readonly=True)
    date_last_document = fields.Boolean(
        readonly=True,
        help="When creating an invoice, set the date to be the same of the previous document, "
        "being it a payment or invoice.",
    )
    diff_partner = fields.Boolean(
        string="Different Partner",
        readonly=True,
        help="Enables use of a different partner than the one set on the operation",
    )

    @api.depends("orig_line_id.dest_line_id")
    def _compute_orig_line(self):
        for record in self.sudo():
            record.orig_line_id = record.orig_line_id if record.orig_line_id.dest_line_id == record else False

    def _inverse_orig_line(self):
        for record in self.sudo():
            record.orig_line_id.dest_line_id = record

    @api.depends("dest_line_id.orig_line_id")
    def _compute_dest_line(self):
        for record in self.sudo():
            record.dest_line_id = record.dest_line_id if record.dest_line_id.orig_line_id == record else False

    def _inverse_dest_line(self):
        for record in self.sudo():
            record.dest_line_id.orig_line_id = record

    def _get_action(self):
        self.ensure_one()
        action = self._get_action_diff_partner()
        if action:
            return action
        method_name = "_get_action_%s" % self.action
        get_action_method = getattr(self, method_name)
        return get_action_method()

    def action_done(self):
        self.state = "done"
        if self.dest_line_id and self.dest_line_id.state == "waiting":
            self.dest_line_id.state = "ready"
        else:
            self.operation_id.action_done()
        if self.dest_line_id and self.dest_line_id.state == "in_progress":
            self.sudo().dest_line_id.action_done()

    def action_in_progress(self):
        self.write({"state": "in_progress"})

    def action_cancel(self):
        lines = self.filtered(lambda line: line.state not in ["done", "cancel"])
        lines.write({"state": "cancel"})
        for line in lines:
            if line.created_operation_id:
                operation = line.created_operation_id.sudo().with_company(line.created_operation_id.company_id)
                operation.action_cancel()
            if (
                line.dest_line_id.operation_id
                and line.operation_id
                and line.dest_line_id.operation_id != line.operation_id
            ):
                dest_line = line.dest_line_id.sudo().with_company(line.dest_line_id.operation_id.company_id)
                dest_line.operation_id.action_cancel()

    def _get_action_move(self):
        ctx = self._context.copy()
        if self.action_id.auto and self.operation_id.amount:
            ctx.update({"amount": self.operation_id.amount})
        action = self.template_id.with_context(**ctx).generate_journal_entry()
        action = self._update_action_context(action)
        return action

    def _get_action_pay(self):
        if self.action_id.auto:
            move = self.orig_line_id._get_latest_move()
            if not move:
                raise UserError(_("Missing invoice to pay"))
            wiz = self.env["account.move.operation.payment"].create(
                {
                    "move_id": move.id,
                    "line_id": self.id,
                }
            )
            return wiz.action_open_register_payment()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account_move_operation.account_move_operation_payment_action"
        )
        action = self._update_action_context(action)
        return action

    def _get_action_reconcile(self):
        if self.action_id.auto:
            move = self._get_latest_move()
            if not move:
                raise UserError(_("Missing invoice to reconcile"))
            wiz = self.env["account.move.operation.reconcile"].create(
                {
                    "partner_id": self.operation_id.partner_id.id,
                    "move_id": move.id,
                    "line_id": self.id,
                    "st_line_id": self.operation_id.st_line_id.id,
                }
            )
            return wiz.action_open_reconcile()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account_move_operation.account_move_operation_reconcile_action"
        )
        action = self._update_action_context(action)
        return action

    def _get_action_operation(self):
        if self.action_id.auto:
            wiz = self.env["account.move.operation.operation"].create(
                {
                    "line_id": self.id,
                    "diff_company_id": self.action_id.operation_type_ids.mapped("company_id")[:1].id,
                    "amount": self.operation_id.amount,
                }
            )
            return wiz.action_create_operation()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account_move_operation.account_move_operation_operation_action"
        )
        action = self._update_action_context(action)
        return action

    def _get_action_diff_partner(self):
        if self.diff_partner and not self._context.get("default_partner_id"):
            action = self.env["ir.actions.actions"]._for_xml_id(
                "account_move_operation.account_move_operation_partner_action"
            )
            action = self._update_action_context(action)
            return action
        return False

    def _get_action_info(self):
        return self.action_done()

    def _update_action_context(self, action):
        context = self._context.copy()
        if "context" in action and isinstance(action["context"], str):
            context.update(safe_eval(action["context"]))
        else:
            context.update(action.get("context", {}))
        action["context"] = context
        action["context"].update(
            {
                "active_model": self._name,
                "active_ids": self.ids,
            }
        )
        return action

    def _get_latest_move(self):
        if self.move_id:
            return self.move_id
        if self.orig_line_id:
            return self.orig_line_id._get_latest_move()
        return False

    def _get_latest_document_date(self):
        doc = self.st_line_id or self.move_id or self.payment_id
        if doc:
            return doc.date or doc.invoice_date
        orig = self.orig_line_id
        if orig:
            if self.operation_id.company_id != orig.operation_id.company_id:
                return orig.sudo().with_company(orig.operation_id.company_id)._get_latest_document_date()
            return orig._get_latest_document_date()
        return False

    def action_open_document(self):
        method_name = "action_open_document_%s" % self.action
        open_document_method = getattr(self, method_name)
        return open_document_method()

    def action_open_document_move(self):
        if not self.move_id:
            return False
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_journal_line")
        action.update(
            {
                "name": _("Entry from template %s", self.template_id.name),
                "res_id": self.move_id.id,
                "views": False,
                "view_id": False,
                "view_mode": "form",
                "context": self.env.context,
            }
        )
        return action

    def action_open_document_pay(self):
        if not self.payment_id:
            return False
        action = {
            "name": _("Payments"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "context": {"create": False},
            "view_mode": "form",
            "res_id": self.payment_id.id,
        }
        return action

    def action_open_document_reconcile(self):
        if not self.st_line_id:
            return False
        action = {
            "name": _("Bank Statement Line"),
            "type": "ir.actions.act_window",
            "res_model": "account.bank.statement.line",
            "context": {"create": False},
            "view_mode": "form",
            "res_id": self.st_line_id.id,
        }
        return action

    def action_open_document_operation(self):
        if not self.created_operation_id:
            return False
        if self.created_operation_id.company_id != self.env.company:
            raise UserError(
                _(
                    "You are trying to access to operation %s which is from a different company %s",
                    self.created_operation_id.name,
                    self.created_operation_id.company_id.name,
                )
            )
        action = {
            "name": _("Accounting Operation"),
            "type": "ir.actions.act_window",
            "res_model": "account.move.operation",
            "context": {"create": False},
            "view_mode": "form",
            "res_id": self.created_operation_id.id,
        }
        return action

    def action_open_document_info(self):
        return self.operation_id.action_open_bank_statement_line()
