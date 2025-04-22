from odoo import api, fields, models
from odoo.fields import Command


class AccountMoveOperationOperation(models.TransientModel):
    _name = "account.move.operation.operation"
    _description = "Wizard to create a sub operation on a different company"

    line_id = fields.Many2one(
        "account.move.operation.line",
        required=True,
    )
    operation_id = fields.Many2one(
        related="line_id.operation_id",
        readonly=True,
    )
    available_company_ids = fields.Many2many("res.company", compute="_compute_available_company_ids")
    diff_company_id = fields.Many2one(
        "res.company",
        required=True,
        domain="[('id', 'in', available_company_ids)]",
    )
    amount = fields.Float(readonly=True)

    @api.depends("line_id.action_id.operation_type_ids")
    def _compute_available_company_ids(self):
        for rec in self:
            rec.available_company_ids = [
                Command.set(rec.line_id.action_id.operation_type_ids.mapped("company_id").ids)
            ]

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

    def action_create_operation(self):
        op_type = self.sudo().line_id.action_id.operation_type_ids.filtered(
            lambda ot: ot.company_id == self.diff_company_id
        )
        operation = self.env["account.move.operation"].sudo().with_company(self.diff_company_id)
        vals = {
            "operation_type_id": op_type.id,
            "partner_id": self.operation_id.partner_id.id,
            "currency_id": self.operation_id.currency_id.id,
        }
        if self.amount:
            vals["amount"] = self.amount
        operation = operation.sudo().create(vals)
        operation.action_start()
        if self.line_id.orig_line_id:
            first_line = operation.line_ids.filtered(lambda ln: not ln.orig_line_id)
            first_line.write({"orig_line_id": self.line_id.orig_line_id.id})
        last_line = operation.line_ids.filtered(lambda ln: not ln.dest_line_id)
        last_line.write({"dest_line_id": self.line_id.id})
        self.line_id.write(
            {
                "state": "in_progress",
                "orig_line_id": last_line.id,
                "created_operation_id": operation.id,
            }
        )
        return False
