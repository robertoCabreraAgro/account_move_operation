from odoo import models
from odoo.osv import expression

from odoo.addons.web.controllers.utils import clean_action


class BankRecWidget(models.Model):
    _inherit = "bank.rec.widget"

    def _prepare_embedded_views_data(self):
        res = super()._prepare_embedded_views_data()
        lines = self.st_line_id.operation_line_ids.filtered(lambda amol: amol.state == "ready" and amol.move_id)
        if not (lines and res.get("amls")):
            return res
        res["amls"].update(
            {
                "domain": expression.AND([res["amls"].get("domain"), [("move_id", "in", lines.move_id.ids)]]),
            }
        )
        return res

    def _action_validate(self):
        res = super()._action_validate()
        op_line = self.st_line_id.operation_line_ids.filtered(lambda amol: amol.state == "ready" and amol.move_id)[:1]
        if op_line:
            op_line.action_done()
        return res

    def _js_action_account_operation(self):
        action = self.st_line_id.action_open_operation_wizard()
        self.return_todo_command = clean_action(action, self.env)
