/**
 * How many rows a page says its list holds, and whether the list stopped
 * counting there (`total_capped`): a list that grows with the organization
 * counts at most ten thousand rows, and a screen then says "more than"
 * (`Pagination`'s `totalCapped`). Zero and false while the page has not
 * arrived.
 */
export function pageTotal(page?: { total: number; total_capped?: boolean }): {
  total: number;
  totalCapped: boolean;
} {
  return {
    total: page?.total ?? 0,
    totalCapped: page?.total_capped ?? false,
  };
}
