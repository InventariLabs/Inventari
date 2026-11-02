import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Input,
  NativeSelect,
  QueryResult,
  ReadOnlyNotice,
  cn,
  extractApiError,
  makeTDynamic,
  useCanWrite,
  useModulePageHeader,
} from "@/module-sdk";
import {
  useWidgets,
  useCreateWidget,
  useUpdateWidget,
  useDeleteWidget,
} from "../hooks/useWidgets";
import { WIDGET_COLORS, type Widget, type WidgetColor } from "../hooks/types";

/**
 * The swatch fill per colour, as static literals.
 *
 * Tailwind only generates the classes it can see in the source, so a class
 * assembled at runtime (`bg-${color}-500`) is never emitted and the swatch
 * renders as an empty circle. A map of literals is the pattern to copy.
 *
 * ui-pattern: palette-identity — the swatch shows a named color the user
 * picked as their widget's identity, not a status, so the success token
 * would be wrong here even though green matches it.
 */
const SWATCH: Record<WidgetColor, string> = {
  blue: "bg-blue-500",
  green: "bg-green-500",
  amber: "bg-amber-500",
  red: "bg-red-500",
  violet: "bg-violet-500",
  slate: "bg-slate-500",
};

function isWidgetColor(value: string): value is WidgetColor {
  return (WIDGET_COLORS as readonly string[]).includes(value);
}

export default function WidgetsPage() {
  const { t } = useTranslation("example_widgets");
  const tDyn = makeTDynamic(t);
  const { setHeader } = useModulePageHeader();
  /**
   * Every module names its permissions the same way, so a page asks about its
   * own module by name. Ask once, at the top, and pass the answer down — every
   * write on the screen has to be behind it, not the first one somebody
   * happened to think of. The API refuses the rest either way; what the reader
   * gets from a button that reaches a refusal is a form filled to the end for
   * nothing.
   */
  const canWrite = useCanWrite("example_widgets");
  const widgets = useWidgets();
  const createWidget = useCreateWidget();
  const updateWidget = useUpdateWidget();
  const deleteWidget = useDeleteWidget();

  useEffect(() => {
    setHeader({
      title: t("page.title"),
      subtitle: t("page.description"),
    });
    return () => setHeader({});
  }, [t, setHeader]);

  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState<WidgetColor>("blue");
  const [pendingDelete, setPendingDelete] = useState<Widget | null>(null);

  const handleCreate = () => {
    if (!newName.trim()) return;
    createWidget.mutate(
      { name: newName.trim(), color: newColor },
      {
        onSuccess: () => {
          setNewName("");
          setNewColor("blue");
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      {/* Says why the screen has no buttons on it. A page that hides its
          actions and says nothing reads as broken, not as a boundary. */}
      <ReadOnlyNotice module="example_widgets" />

      {/* Create form */}
      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{t("actions.add")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                {/* `label` on the control, not a `<label>` above it: the
                  component owns the id both sides need to agree on. */}
                <Input
                  label={t("fields.name")}
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={t("fields.name")}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                />
              </div>
              <div className="flex items-end gap-2 sm:w-44">
                {/* A closed set of values gets a control with a closed set of
                  values. A free-text field accepted "grass green" and drew a
                  blank circle for it. */}
                <NativeSelect
                  label={t("fields.color")}
                  wrapperClassName="flex-1"
                  value={newColor}
                  onChange={(e) => setNewColor(e.target.value as WidgetColor)}
                >
                  {WIDGET_COLORS.map((color) => (
                    <option key={color} value={color}>
                      {tDyn(`colors.${color}`)}
                    </option>
                  ))}
                </NativeSelect>
                <span
                  aria-hidden="true"
                  className={cn(
                    "mb-0.5 h-6 w-6 shrink-0 rounded-full border border-border",
                    SWATCH[newColor],
                  )}
                />
              </div>
              <Button onClick={handleCreate} disabled={!newName.trim()}>
                <Plus className="h-4 w-4 mr-1" />
                {t("actions.add")}
              </Button>
            </div>
            {/* A refused write carries a sentence in the reader's language in
                the response; `extractApiError` reads it, and falls back to
                the module's own text when there is none (a 5xx, a network
                failure). Showing it is what tells the reader why nothing
                was saved. */}
            {createWidget.isError && (
              <p role="alert" className="mt-3 text-sm text-on-danger">
                {extractApiError(
                  createWidget.error,
                  t("common:errors.somethingWentWrong"),
                )}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Widget list — QueryResult carries the spinner and the retry, so the
          module has a loading and an error state without writing either. */}
      <QueryResult query={widgets}>
        {({ items }) =>
          items.length === 0 ? (
            <p className="text-on-muted text-center py-8">
              {t("messages.empty")}
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((widget) => (
                <WidgetCard
                  key={widget.id}
                  widget={widget}
                  canWrite={canWrite}
                  onUpdate={(patch) =>
                    updateWidget.mutate({ id: widget.id, data: patch })
                  }
                  onDelete={() => setPendingDelete(widget)}
                />
              ))}
            </div>
          )
        }
      </QueryResult>

      <ConfirmDialog
        open={pendingDelete !== null}
        variant="danger"
        title={t("messages.confirmDeleteTitle")}
        message={t("messages.confirmDelete", {
          name: pendingDelete?.name ?? "",
        })}
        confirmLabel={t("actions.delete")}
        onConfirm={() => {
          if (pendingDelete) deleteWidget.mutate(pendingDelete.id);
          setPendingDelete(null);
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

function WidgetCard({
  widget,
  canWrite,
  onUpdate,
  onDelete,
}: {
  widget: Widget;
  canWrite: boolean;
  onUpdate: (data: { quantity: number }) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation("example_widgets");
  const tDyn = makeTDynamic(t);
  const known = isWidgetColor(widget.color);

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-semibold">{widget.name}</h3>
            <p className="text-sm text-on-muted">
              {t("fields.color")}:{" "}
              {known ? tDyn(`colors.${widget.color}`) : widget.color}
            </p>
          </div>
          <div
            aria-hidden="true"
            className={cn(
              "w-6 h-6 rounded-full border border-border",
              known ? SWATCH[widget.color as WidgetColor] : "bg-surface-inset",
            )}
          />
        </div>
        <div className="mt-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm">{t("fields.quantity")}:</span>
            {/* Changing a quantity is a write like any other. Two steppers
                and a delete: all three go, or the reader finds the boundary
                by tripping over it. */}
            {canWrite && (
              <Button
                variant="outline"
                size="sm"
                aria-label={t("actions.decrease")}
                onClick={() =>
                  onUpdate({ quantity: Math.max(0, widget.quantity - 1) })
                }
              >
                -
              </Button>
            )}
            <span className="font-mono w-8 text-center">{widget.quantity}</span>
            {canWrite && (
              <Button
                variant="outline"
                size="sm"
                aria-label={t("actions.increase")}
                onClick={() => onUpdate({ quantity: widget.quantity + 1 })}
              >
                +
              </Button>
            )}
          </div>
          {canWrite && (
            <Button
              variant="ghostDanger"
              size="sm"
              aria-label={t("actions.delete")}
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
