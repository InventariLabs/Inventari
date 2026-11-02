import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { ALL_PEOPLE, NOBODY, type PersonFilter } from "./boardColumns";

export interface BoardPerson {
  id: string;
  name: string;
}

/**
 * The chips that choose whose cards the board shows. Each person's chip, and
 * "Unassigned", is also where a card is dropped to give it to them (or to take
 * it back); "Everyone" only filters. Giving a card by keyboard is the select
 * on the card itself.
 */
export function BoardPeople({
  people,
  value,
  onChange,
  dropEnabled,
  onDropOn,
}: {
  people: BoardPerson[];
  value: PersonFilter;
  onChange: (person: PersonFilter) => void;
  /** Whether a card is being dragged right now. */
  dropEnabled: boolean;
  /** The card is dropped on a person's chip (`null`: on "Unassigned"). */
  onDropOn: (assigneeId: string | null) => void;
}) {
  const { t } = useTranslation("warehouse");
  const [over, setOver] = useState<string | null>(null);

  const chip = (
    id: PersonFilter,
    label: string,
    assigneeId?: string | null,
  ) => {
    const droppable = dropEnabled && assigneeId !== undefined;
    const selected = value === id;
    return (
      <Button
        key={id}
        type="button"
        variant="outline"
        size="sm"
        aria-pressed={selected}
        onClick={() => onChange(id)}
        onDragOver={(event) => {
          if (!droppable) return;
          event.preventDefault();
          setOver(id);
        }}
        onDragLeave={() =>
          setOver((current) => (current === id ? null : current))
        }
        onDrop={(event) => {
          if (!droppable) return;
          event.preventDefault();
          setOver(null);
          onDropOn(assigneeId);
        }}
        className={cn(
          "rounded-full",
          selected &&
            "border-primary-500 bg-primary-50 font-semibold text-on hover:bg-primary-50",
          over === id && "ring-2 ring-primary-500",
        )}
      >
        {label}
      </Button>
    );
  };

  return (
    <div
      role="group"
      aria-label={t("board.people.label")}
      className="flex flex-wrap gap-1.5"
    >
      {chip(ALL_PEOPLE, t("board.people.all"))}
      {people.map((person) => chip(person.id, person.name, person.id))}
      {chip(NOBODY, t("board.people.none"), null)}
    </div>
  );
}
