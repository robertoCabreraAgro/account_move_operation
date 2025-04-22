from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class AccountInvoiceTemplateLineRun(models.TransientModel):
    _name = "account.invoice.template.line.run"
    _description = "Wizard to generate invoice lines from template"

    wizard_id = fields.Many2one("account.invoice.template.run", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id")
    company_currency_id = fields.Many2one(related="wizard_id.company_id.currency_id", string="Company Currency")
    line_id = fields.Many2one("account.move.template.line", required=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", "Partner")
    product_id = fields.Many2one("product.product")
    product_uom_id = fields.Many2one(
        "uom.uom",
        "Unit of Measure",
        compute="_compute_product_uom_id",
        store=True,
        readonly=False,
        precompute=True,
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_uom_category_id = fields.Many2one(related="product_id.uom_id.category_id", default=1)
    product_uom_qty = fields.Float("Quantity", digits="Product Unit of Measure")
    name = fields.Char(readonly=True)
    account_id = fields.Many2one("account.account", required=True, readonly=True)
    tax_ids = fields.Many2many("account.tax", string="Taxes", readonly=True)
    type = fields.Selection(
        [
            ("input", "User input"),
            ("computed", "Computed"),
        ],
    )
    amount = fields.Monetary(currency_field="company_currency_id", required=True)

    def _compute_line(self):
        safe_eval_dict = {}
        for seq, amount in self.wizard_id.template_id.line_ids_integrity.items():
            safe_eval_dict["L%d" % seq] = amount
        try:
            val = safe_eval(self.line_id.python_code, safe_eval_dict)
        except ValueError as err:
            raise UserError(
                _(
                    "Impossible to compute the formula of line with sequence %(sequence)s "
                    "(formula: %(code)s). Check that the lines used in the formula "
                    "really exists and have a lower sequence than the current "
                    "line.",
                    sequence=self.line_id.sequence,
                    code=self.line_id.python_code,
                )
            ) from err
        except SyntaxError as err:
            raise UserError(
                _(
                    "Impossible to compute the formula of line with sequence %(sequence)s "
                    "(formula: %(code)s): the syntax of the formula is wrong.",
                    sequence=self.line_id.sequence,
                    code=self.line_id.python_code,
                )
            ) from err
        self.amount = self.company_currency_id.round(val)

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    def _update_account_on_negative(self, vals):
        if not self.line_id.opt_account_id:
            return vals
        for key in ["debit", "credit"]:
            if vals[key] < 0:
                ikey = (key == "debit") and "credit" or "debit"
                vals["account_id"] = self.line_id.opt_account_id.id
                vals[ikey] = abs(vals[key])
                vals[key] = 0
        return vals

    def _prepare_move_line_vals(self):
        date_maturity = False
        if self.line_id.payment_term_id:
            pterm_list = self.line_id.payment_term_id.compute(value=1, date_ref=self.wizard_id.date)
            date_maturity = max(line[0] for line in pterm_list)
        debit = self.line_id.move_line_type == "dr"
        price_unit = False
        if self.line_id.template_id.move_type != "entry" and self.product_id:
            price_unit = self.amount / self.product_uom_qty if self.product_uom_qty else self.amount
        vals = {
            "partner_id": self.wizard_id.partner_id.id or self.partner_id.id,
            "date_maturity": date_maturity or self.wizard_id.date,
            "product_id": self.product_id.id or False,
            "product_uom_id": self.product_uom_id.id or False,
            "quantity": self.product_uom_qty,
            "price_unit": price_unit,
            "name": self.name,
            "account_id": self.account_id.id,
            "analytic_distribution": self.line_id.analytic_distribution,
            "credit": not debit and self.amount or 0.0,
            "debit": debit and self.amount or 0.0,
            "tax_repartition_line_id": self.line_id.tax_repartition_line_id.id or False,
        }
        if self.tax_ids:
            vals["tax_ids"] = [Command.set(self.tax_ids.ids)]
            tax_repartition = "refund_tax_id" if self.line_id.is_refund else "invoice_tax_id"
            atrl_ids = self.env["account.tax.repartition.line"].search(
                [
                    (tax_repartition, "in", self.tax_ids.ids),
                    ("repartition_type", "=", "base"),
                ]
            )
            vals["tax_tag_ids"] = [Command.set(atrl_ids.mapped("tag_ids").ids)]
        if self.line_id.tax_repartition_line_id:
            vals["tax_tag_ids"] = [Command.set(self.line_id.tax_repartition_line_id.tag_ids.ids)]
        overwrite = self._context.get("overwrite", {})
        move_line_vals = overwrite.get("L{}".format(self.line_id.sequence), {})
        vals.update(move_line_vals)
        vals = self._update_account_on_negative(vals)
        return vals

    @api.onchange("product_id")
    def _onchange_product(self):
        self.update({"name": self.product_id.display_name, "tax_ids": [Command.set(self.product_id.taxes_id.ids)]})
