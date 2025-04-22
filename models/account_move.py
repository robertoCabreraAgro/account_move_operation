from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        opertation_line_obj = self.env["account.move.operation.line"]
        res = super().action_post()
        for rec in self.filtered(lambda am: am.state == "posted"):
            line = opertation_line_obj.search(
                [("action", "=", "move"), ("state", "=", "in_progress"), ("move_id", "=", rec.id)], limit=1
            )
            if line:
                line.action_done()
        return res
