from odoo import _, api, fields, models


class AccountBankStatementOperation(models.TransientModel):
    _name = "account.bank.statement.operation"
    _description = "Wizard to create an operation from a bank statement"

    st_line_id = fields.Many2one(
        "account.bank.statement.line",
        required=True,
    )
    operation_type_id = fields.Many2one(
        "account.move.operation.type",
        domain="[('from_bank_statement', '=', True), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    count_operations = fields.Integer(compute="_compute_count_operations")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if self.env.context.get("active_model") == "account.bank.statement.line" and "active_ids" in self.env.context:
            line = self.env[self.env.context["active_model"]].browse(self.env.context["active_ids"])[:1]
            defaults.update(
                {
                    "st_line_id": line.id,
                    "company_id": line.company_id.id,
                }
            )
        elif self.env.context.get("active_model") == "bank.rec.widget" and "active_ids" in self.env.context:
            widget = self.env[self.env.context["active_model"]].browse(self.env.context["active_ids"])[:1]
            defaults.update(
                {
                    "st_line_id": widget.st_line_id.id,
                    "company_id": widget.st_line_id.company_id.id,
                }
            )
        return defaults

    def action_create_operation(self):
        operation = self.env["account.move.operation"].create(
            {
                "operation_type_id": self.operation_type_id.id,
                "st_line_id": self.st_line_id.id,
                "partner_id": self.st_line_id.partner_id.id,
                "currency_id": self.st_line_id.currency_id.id,
                "amount": self.st_line_id.amount,
            }
        )
        return {
            "name": _("Operation"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_model": "account.move.operation",
            "res_id": operation.id,
            "target": "current",
        }

    def open_existing_operations(self):
        action = self.env["ir.actions.actions"]._for_xml_id("account_move_operation.account_move_operation_action")
        action["domain"] = [("id", "in", self.st_line_id.operation_ids.ids)]
        action["views"] = [
            ((view_id, "list") if view_type == "tree" else (view_id, view_type))
            for view_id, view_type in action["views"]
        ]
        return action

    @api.depends("st_line_id.operation_ids")
    def _compute_count_operations(self):
        for rec in self:
            rec.count_operations = len(rec.st_line_id.operation_ids)
