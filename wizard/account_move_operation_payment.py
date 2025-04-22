from odoo import api, fields, models
from odoo.tools.safe_eval import safe_eval


class AccountMoveOperationPayment(models.TransientModel):
    _name = "account.move.operation.payment"
    _description = "Wizard to generate payments from operation"
    _check_company_auto = True

    move_id = fields.Many2one(
        "account.move",
        required=True,
        check_company=True,
        domain="[('company_id', '=', company_id)]",
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

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if self.env.context.get("active_model") == "account.move.operation.line" and "active_ids" in self.env.context:
            line = self.env[self.env.context["active_model"]].browse(self.env.context["active_ids"])[:1]
            move = line.orig_line_id._get_latest_move()
            defaults.update(
                {
                    "move_id": move and move.id or False,
                    "line_id": line.id,
                }
            )
        return defaults

    def action_open_register_payment(self):
        action = self.move_id.action_register_payment()
        line = self.line_id
        context = self._context.copy()
        if "context" in action and isinstance(action["context"], str):
            context.update(safe_eval(action["context"]))
        else:
            context.update(action.get("context", {}))
        action["context"] = context
        action["context"].update(
            {
                "default_journal_id": line.journal_id.id,
                "operation_id": line.operation_id.id,
                "operation_line_id": line.id,
            }
        )
        return action
