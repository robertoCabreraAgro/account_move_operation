from odoo import _, fields, models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    operation_line_ids = fields.One2many("account.move.operation.line", "st_line_id", readonly=True)
    operation_ids = fields.One2many("account.move.operation", "st_line_id", readonly=True)

    def action_open_operation_wizard(self):
        view = self.env.ref("account_move_operation.account_bank_statement_operation_form")
        return {
            "name": _("Account Operation"),
            "type": "ir.actions.act_window",
            "res_model": "account.bank.statement.operation",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "context": {
                "active_model": self._name,
                "active_id": self.id,
                "active_ids": self.ids,
            },
        }
