from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMoveOperationFromMove(models.TransientModel):
    _name = "account.move.operation.from.move"
    _description = "Create Operation from Journal Entry"

    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Journal Entry",
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        required=True,
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
    )
    ref = fields.Char(
        string="Reference",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id.id,
    )
    move_type = fields.Selection(
        related="move_id.move_type",
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    operation_type_id = fields.Many2one(
        comodel_name="account.move.operation.type",
        string="Operation Type",
        required=True,
        domain="[('company_id', 'in', (company_id, False)), ('sub_operation', '=', False)]",
    )
    completed_template_ids = fields.Many2many(
        comodel_name="account.move.template",
        string="Already Completed Templates",
        help="Select templates that are already completed manually or in previous operations."
    )
    operation_preview_ids = fields.One2many(
        comodel_name="account.move.operation.from.move.line",
        inverse_name="wizard_id",
        string="Operation Steps Preview",
        readonly=True,
    )
    show_warning = fields.Boolean(
        string="Show Warning",
        compute="_compute_show_warning",
        store=False,
    )
    warning_message = fields.Html(
        string="Warning",
        compute="_compute_show_warning",
        store=False,
    )
    
    @api.depends('operation_type_id', 'move_type')
    def _compute_show_warning(self):
        for wizard in self:
            wizard.show_warning = False
            wizard.warning_message = False
            
            if not wizard.operation_type_id or wizard.move_type == 'entry':
                continue
                
            # Verificar si hay una plantilla que coincida con el tipo de documento
            origin_matched = False
            for line in wizard.operation_preview_ids:
                if line.template_id and line.template_id.move_type == wizard.move_type:
                    origin_matched = True
                    break
                    
            if not origin_matched:
                move_type_label = dict(wizard.move_id._fields['move_type'].selection).get(wizard.move_type)
                wizard.show_warning = True
                wizard.warning_message = _(
                    '<div class="alert alert-warning" role="alert">'
                    'The selected operation does not have any template that matches the '
                    'origin document type (<strong>%s</strong>). '
                    '<br/>This may lead to invalid operation flow.'
                    '</div>',
                    move_type_label
                )
    
    @api.onchange('operation_type_id')
    def _onchange_operation_type(self):
        """Al cambiar el tipo de operación, actualizamos la vista previa de pasos."""
        self.operation_preview_ids = [(5, 0, 0)]
        
        if not self.operation_type_id:
            return
            
        # Generar una vista previa de los pasos a ejecutar
        preview_vals = []
        origin_template = None
        origin_type_matched = False
        
        # Recorrer todas las acciones del tipo de operación para verificar compatibilidad
        for idx, action in enumerate(self.operation_type_id.action_ids):
            status = 'pending'
            
            # Solo las acciones de tipo 'move' tienen plantilla
            if action.action == 'move' and action.template_id:
                # Verificar si la plantilla ya está marcada como completada
                if action.template_id in self.completed_template_ids:
                    status = 'completed'
                
                # Verificar si el asiento origen coincide con el tipo de esta plantilla
                if not origin_type_matched and action.template_id.move_type == self.move_type:
                    origin_template = action.template_id
                    origin_type_matched = True
                    status = 'origin'
            
            preview_vals.append((0, 0, {
                'sequence': idx + 1,
                'name': action.name,
                'action': action.action,
                'template_id': action.template_id.id if action.template_id else False,
                'status': status,
            }))
        
        self.operation_preview_ids = preview_vals
        
        # Si no encontramos un template que coincida con el tipo de documento de origen,
        # mostramos una advertencia pero no impedimos continuar
        if not origin_type_matched and self.move_type != 'entry':
            # La advertencia se mostrará a través del campo computed warning_message
            pass
    
    def action_create_operation(self):
        """Crear una nueva operación basada en el asiento origen."""
        self.ensure_one()
        
        # Verificar que al menos un template del flujo coincida con el tipo de documento
        origin_matched = False
        for line in self.operation_preview_ids:
            if line.status == 'origin' and line.template_id:
                origin_matched = True
                break
                
        if not origin_matched and self.move_type != 'entry':
            raise ValidationError(_(
                'The selected operation does not include any template that matches the origin document type (%s). '
                'Cannot continue with this operation flow.',
                dict(self.move_id._fields['move_type'].selection).get(self.move_type)
            ))
        
        # Crear la operación
        operation = self.env['account.move.operation'].create({
            'operation_type_id': self.operation_type_id.id,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'amount': self.amount,
            'reference': self.ref,
        })
        
        # Iniciar la operación
        operation.action_start()
        
        # Marcar como completadas las plantillas seleccionadas manualmente
        self._process_completed_templates(operation)
        
        # Asociar el asiento origen a la línea de operación correspondiente
        self._associate_origin_document(operation)
        
        # Redirigir a la operación creada
        return {
            'name': _('Operation'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.operation',
            'res_id': operation.id,
            'view_mode': 'form',
            'target': 'current',
        }
        
    def _process_completed_templates(self, operation):
        """Marcar como completadas las plantillas seleccionadas manualmente."""
        for line in operation.line_ids.filtered(lambda l: 
            l.action == 'move' and 
            l.template_id in self.completed_template_ids and
            l.state != 'done'
        ):
            # Modificamos el estado directamente para evitar efectos secundarios
            line.write({
                'state': 'done',
                'skip_auto_process': True,
            })
            
            # Si la siguiente línea está en estado "waiting", la ponemos en "ready"
            if line.dest_line_id and line.dest_line_id.state == 'waiting':
                line.dest_line_id.state = 'ready'
                
    def _associate_origin_document(self, operation):
        """Asociar el asiento origen a la línea de operación correspondiente."""
        # Buscar la línea que corresponde al tipo de documento de origen
        origin_line = operation.line_ids.filtered(lambda l: 
            l.action == 'move' and 
            l.template_id and 
            l.template_id.move_type == self.move_type and
            l.state != 'done'
        )
        
        if origin_line:
            # Tomamos la primera línea que coincida
            origin_line = origin_line[0]
            origin_line.write({
                'move_id': self.move_id.id,
                'state': 'done',
            })
            
            # Si la siguiente línea está en estado "waiting", la ponemos en "ready"
            if origin_line.dest_line_id and origin_line.dest_line_id.state == 'waiting':
                origin_line.dest_line_id.state = 'ready'


class AccountMoveOperationFromMoveLine(models.TransientModel):
    _name = "account.move.operation.from.move.line"
    _description = "Operation from Move Preview Line"
    _order = "sequence"
    
    wizard_id = fields.Many2one(
        comodel_name="account.move.operation.from.move",
        string="Wizard",
        required=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )
    name = fields.Char(
        string="Step Name",
        required=True,
    )
    action = fields.Selection(
        selection=[
            ("move", "Create Journal Entry"),
            ("pay", "Create Payment"),
            ("reconcile", "Reconcile Payment"),
            ("operation", "Create Operation"),
            ("info", "Information"),
        ],
        string="Action",
        required=True,
    )
    template_id = fields.Many2one(
        comodel_name="account.move.template",
        string="Template",
    )
    status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("completed", "Already Completed"),
            ("origin", "Origin Document"),
        ],
        string="Status",
        default="pending",
        required=True,
    ) 