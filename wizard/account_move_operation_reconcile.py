from odoo import api, fields, models


class AccountMoveOperationReconcile(models.TransientModel):
    _name = "account.move.operation.reconcile"
    _description = "Wizard to generate reconcile bank statement to account move"
    _check_company_auto = True

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
    )
    move_id = fields.Many2one(
        "account.move",
        required=True,
        domain=[
            ("partner_id", "=", partner_id),
            ("state", "!=", "cancel"),
            ("payment_state", "!=", "paid"),
        ],
    )
    st_line_id = fields.Many2one(
        "account.bank.statement.line",
        required=True,
        domain=[
            "|",
            ("partner_id", "=", partner_id),
            ("partner_id", "=", False),
        ],
    )
    line_id = fields.Many2one(
        "account.move.operation.line",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related="st_line_id.currency_id", readonly=True)
    amount = fields.Monetary(related="st_line_id.amount", readonly=True)
    statement_id = fields.Many2one("account.bank.statement", related="st_line_id.statement_id", readonly=True)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if self.env.context.get("active_model") == "account.move.operation.line" and "active_ids" in self.env.context:
            line = self.env[self.env.context["active_model"]].browse(self.env.context["active_ids"])[:1]
            operation = line.operation_id
            st_line_id = operation.st_line_id or line.st_line_id
            move = line._get_latest_move()
            defaults.update(
                {
                    "move_id": move and move.id or False,
                    "line_id": line.id,
                    "partner_id": move and move.partner_id.id or operation.partner_id.id,
                    "st_line_id": st_line_id.id or False,
                }
            )
        return defaults

    def action_open_reconcile(self):
        self.ensure_one()
        st_line_id = self.st_line_id
        line = self.line_id
        line.st_line_id = st_line_id
        line.move_id = self.move_id
        return st_line_id._action_open_bank_reconciliation_widget(
            name=st_line_id.name,
            default_context={
                "default_statement_id": st_line_id.statement_id.id,
                "default_journal_id": st_line_id.journal_id.id,
                "default_st_line_id": st_line_id.id,
                "search_default_id": st_line_id.id,
            },
            extra_domain=[("id", "=", st_line_id.id)],
        )
