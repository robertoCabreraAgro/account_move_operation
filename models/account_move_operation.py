from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
    diff_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Diff Partner",
        domain=["|", ("parent_id", "=", False), ("is_company", "=", True)],
    )
    target_company_id = fields.Many2one(
        comodel_name="res.company",
        string="Target Company",
    )
    operation_type_id = fields.Many2one(
        comodel_name="account.move.operation.type",
        string="Type",
        required=True,
        domain="[('company_id', 'in', (company_id, False)), ('sub_operation', '=', False)]",
        index=True,
    )
    diff_partner = fields.Boolean(
        related="operation_type_id.diff_partner",
    )
    multicompany = fields.Boolean(
        related="operation_type_id.multicompany",
    )
    multicompany_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
        help="Leave this field empty if this route is shared between all companies",
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
    from_bank_statement = fields.Boolean(
        related="operation_type_id.from_bank_statement"
    )
    line_ids = fields.One2many(
        "account.move.operation.line", "operation_id", readonly=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "company_id" in vals:
                self = self.sudo().with_company(vals["company_id"])
            if vals.get("name", _("New")) == _("New"):
                seq_date = (
                    fields.Datetime.context_timestamp(
                        self, fields.Datetime.to_datetime(vals["date"])
                    )
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
                    "currency_id": self.st_line_id.currency_id.id
                    or self.currency_id.id,
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

    def action_cancel(self):
        self.ensure_one()
        if self.state in ["done", "cancel"]:
            return

        self.state = "cancel"
        self.line_ids.action_cancel()

    def action_done(self):
        self.ensure_one()
        if self.state != "in_progress":
            return

        self.state = "done"

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
        for action in self.operation_type_id.action_ids:
            vals_list.append(self._get_line_vals(action))
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
            "operation_id": self.id,
            "date_last_document": rule.date_last_document,
            "diff_partner": rule.diff_partner,
            "action_id": rule.id,
            "multicompany": rule.multicompany,
        }
        return vals

    def _get_next_action(self):
        in_progress_line = self.line_ids.filtered(
            lambda line: line.state == "in_progress"
        )[:1]
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

            return in_progress_line.action_view_document()

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
