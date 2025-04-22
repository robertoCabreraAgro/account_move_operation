from odoo import api, fields, models


class AccountMoveOperationPartner(models.TransientModel):
    _name = "account.move.operation.partner"
    _description = "Wizard to select different partner from operation"

    line_id = fields.Many2one(
        "account.move.operation.line",
        required=True,
    )
    operation_id = fields.Many2one(
        related="line_id.operation_id",
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if self.env.context.get("active_model") == "account.move.operation.line" and "active_ids" in self.env.context:
            line = self.env[self.env.context["active_model"]].browse(self.env.context["active_ids"])[:1]
            defaults.update(
                {
                    "line_id": line.id,
                }
            )
        return defaults

    def action_open_wizard(self):
        ctx = {}
        ctx["default_partner_id"] = self.partner_id.id
        return self.operation_id.with_context(**ctx)._get_next_action()
