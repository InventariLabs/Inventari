import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Boxes } from "lucide-react";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { QueryResult } from "@/components/ui/QueryResult";
import { EmptyState } from "@/components/ui/EmptyState";
import { Pagination } from "@/module-sdk";
import { useDebounce } from "@/module-sdk";
import { useStockQuants } from "../hooks/useStockQuants";
import { StockQuantsTable } from "./stock/StockQuantsTable";
import { StockQuantCards } from "./stock/StockQuantCards";

export default function BackgroundStockPanel() {
  const { t } = useTranslation("inventory");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const debouncedSearch = useDebounce(search, 300);
  const query = useStockQuants({ search: debouncedSearch, limit: 25, offset });
  return (
    <div className="space-y-4">
      <ListControlBar
        search={{
          value: search,
          onChange: (value) => {
            setSearch(value);
            setOffset(0);
          },
          placeholder: t("stock.searchPlaceholder"),
        }}
      />
      <QueryResult query={query}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState
              variant="compact"
              icon={Boxes}
              title={t(
                search ? "stock.empty.filteredTitle" : "stock.empty.title",
              )}
            />
          ) : (
            <>
              <div className="hidden sm:block">
                <StockQuantsTable rows={page.items} linkToBatches={false} />
              </div>
              <div className="sm:hidden">
                <StockQuantCards rows={page.items} />
              </div>
              <Pagination
                skip={offset}
                limit={25}
                total={page.total}
                onPrev={() => setOffset((value) => Math.max(0, value - 25))}
                onNext={() => setOffset((value) => value + 25)}
              />
            </>
          )
        }
      </QueryResult>
    </div>
  );
}
