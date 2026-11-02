/** The match keys a putaway rule can carry, shared by the dialog and its
 * match section so neither owns the other's shape. */
export interface PutawayMatchForm {
  product_template_id: string;
  category_id: string;
  context_tag: string;
  location_type_code: string;
}
