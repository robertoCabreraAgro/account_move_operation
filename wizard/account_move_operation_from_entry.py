from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMoveOperationFromEntry(models.TransientModel):
    _name = "account.move.operation.from.entry"
    _description = "Start Operation From Existing Entry"

    move_id = fields.Many2one(
        "account.move",
        string="Source Entry",
        required=True,
        readonly=True,
    )
    operation_type_id = fields.Many2one(
        "account.move.operation.type",
        string="Operation Type",
        required=True,
        domain="[('company_id', 'in', (company_id, False)), ('sub_operation', '=', False)]",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        required=True,
    )
    reference = fields.Char(string="Reference")
    amount = fields.Monetary(string="Amount", currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    action_line_ids = fields.One2many(
        "account.move.operation.from.entry.line",
        "wizard_id",
        string="Actions",
    )
    diff_partner = fields.Boolean(
        related="operation_type_id.diff_partner",
    )
    multicompany = fields.Boolean(
        related="operation_type_id.multicompany",
    )
    diff_partner_id = fields.Many2one(
        "res.partner",
        string="On Behalf of",
        domain=["|", ("parent_id", "=", False), ("is_company", "=", True)],
    )
    target_company_id = fields.Many2one(
        "res.company",
        string="Target Company",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "account.move" and self.env.context.get("active_id"):
            move = self.env["account.move"].browse(self.env.context.get("active_id"))
            res.update({
                "move_id": move.id,
                "partner_id": move.partner_id.id,
                "reference": move.ref or move.name,
                "currency_id": move.currency_id.id,
                "amount": move.amount_total if hasattr(move, "amount_total") 
                    else sum(move.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')).mapped('amount_currency')),
                "company_id": move.company_id.id,
            })
        return res
    
    @api.onchange("operation_type_id")
    def _onchange_operation_type_id(self):
        """Load action lines based on operation type"""
        self.ensure_one()
        self.action_line_ids = [(5, 0, 0)]
        
        if not self.operation_type_id:
            return
            
        # Get template actions from operation type
        actions = self.operation_type_id.action_ids.filtered(lambda a: a.active)
        
        # Try to identify which template corresponds to our source document
        matched_action = self._identify_matching_action(actions)
        
        # Create action lines
        vals_list = []
        for action in actions:
            is_source = action == matched_action
            vals_list.append({
                'action_id': action.id,
                'name': action.name,
                'executed': is_source,
                'document_id': self.move_id.id if is_source else False,
            })
        
        self.action_line_ids = [(0, 0, vals) for vals in vals_list]
    
    def _identify_matching_action(self, actions):
        """Try to identify which action matches our source document"""
        self.ensure_one()
        move = self.move_id
        
        # Check move type for invoices
        if hasattr(move, 'move_type'):
            move_type = move.move_type
            # For invoices, match with move templates that generate invoices
            if move_type in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
                for action in actions.filtered(lambda a: a.action == 'move'):
                    if action.template_id:
                        # Here you'd need logic to determine if the template would create
                        # the same type of invoice. This could be based on template description,
                        # journal, or custom fields you might add to templates.
                        # For now using a simple heuristic based on name
                        template_name = action.template_id.name.lower()
                        if (move_type == 'out_invoice' and ('customer' in template_name or 'sale' in template_name)) or \
                           (move_type == 'in_invoice' and ('vendor' in template_name or 'purchase' in template_name)) or \
                           (move_type == 'out_refund' and ('credit' in template_name and ('customer' in template_name or 'sale' in template_name))) or \
                           (move_type == 'in_refund' and ('credit' in template_name and ('vendor' in template_name or 'purchase' in template_name))):
                            return action
        
        # For payments
        if self.env['account.payment']._name_search(move.name, [], 'like', limit=1):
            for action in actions.filtered(lambda a: a.action == 'pay'):
                return action
                
        # If nothing specifically matched, try to find any move action
        return actions.filtered(lambda a: a.action == 'move')[:1]
    
    def action_create_operation(self):
        """Create an operation and initialize it with our existing document"""
        self.ensure_one()
        
        # Check if at least one action is not executed
        if all(line.executed for line in self.action_line_ids):
            raise ValidationError(_("All actions are already executed. No need to create an operation."))
        
        # Create operation
        operation_vals = {
            "name": _("New"),
            "operation_type_id": self.operation_type_id.id,
            "partner_id": self.partner_id.id,
            "reference": self.reference,
            "amount": self.amount,
            "currency_id": self.currency_id.id,
            "company_id": self.company_id.id,
        }
        
        # Add diff partner if needed
        if self.diff_partner and self.diff_partner_id:
            operation_vals["diff_partner_id"] = self.diff_partner_id.id
        
        # Add target company if multicompany
        if self.multicompany and self.target_company_id:
            operation_vals["target_company_id"] = self.target_company_id.id
        
        operation = self.env["account.move.operation"].create(operation_vals)
        
        # Start operation to create lines
        operation.action_start()
        
        # Mark executed actions in the operation lines
        for wizard_line in self.action_line_ids.filtered(lambda l: l.executed):
            operation_line = operation.line_ids.filtered(
                lambda l: l.action_id.id == wizard_line.action_id.id
            )
            if operation_line:
                # Set document connection and mark as done
                if wizard_line.action_id.action == 'move':
                    operation_line.move_id = wizard_line.document_id.id
                elif wizard_line.action_id.action == 'pay':
                    operation_line.payment_id = wizard_line.document_id.id
                
                operation_line.state = 'done'
                
                # Update next line to ready
                next_line = operation.line_ids.filtered(
                    lambda l: l.orig_line_id.id == operation_line.id
                )
                if next_line:
                    next_line.state = 'ready'
        
        # Open the created operation
        return {
            'name': _('Account Operation'),
            'view_mode': 'form',
            'res_model': 'account.move.operation',
            'res_id': operation.id,
            'type': 'ir.actions.act_window',
        }


class AccountMoveOperationFromEntryLine(models.TransientModel):
    _name = "account.move.operation.from.entry.line"
    _description = "Operation From Entry Lines"
    
    wizard_id = fields.Many2one(
        "account.move.operation.from.entry",
        string="Wizard",
    )
    action_id = fields.Many2one(
        "account.move.operation.action",
        string="Action",
        required=True,
    )
    name = fields.Char(string="Description", required=True)
    executed = fields.Boolean(string="Already Executed")
    document_id = fields.Many2one(
        "account.move",
        string="Existing Document",
    )