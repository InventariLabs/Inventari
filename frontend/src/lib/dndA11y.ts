import { useTranslation } from "react-i18next";
import {
  KeyboardCode,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type Active,
  type Announcements,
  type Over,
  type ScreenReaderInstructions,
  type SensorDescriptor,
  type SensorOptions,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";

/**
 * The data key every draggable and droppable may carry to name itself in
 * human words — the name the reader sees on the element, not the machine
 * identifier dnd-kit would otherwise print:
 *
 *     useDraggable({ id: `recipe:${recipe.id}`, data: { [DND_LABEL]: recipe.name } })
 *
 * Announcements read this key through {@link dragLabel}. When it is absent
 * the announcement falls back to `String(node.id)` — a slug or a UUID is a
 * bad name, but silence is worse, and a context that carries no names is
 * exactly the pre-2324 state this fallback keeps legible. Recorded here
 * because "no label" is a decision, not an oversight.
 */
export const DND_LABEL = "dndLabel";

/** The node's name in the reader's words, or its machine id when it has none. */
function dragLabel(node: Active | Over | null | undefined): string {
  const label = node?.data?.current?.[DND_LABEL];
  return typeof label === "string" && label.trim() !== ""
    ? label
    : String(node?.id ?? "");
}

/**
 * Screen-reader words for every DndContext in the app, in the reader's
 * language. Without them dnd-kit answers with its own English defaults — a
 * hidden instruction element under every draggable and an assertive live
 * region announcing pickups and drops — so a Polish reader heard English
 * from a UI that otherwise speaks their language.
 *
 * The result is the whole `accessibility` prop of `DndContext` — the
 * library takes announcements and instructions through that one object,
 * not as top-level props (a top-level spread compiles and silently does
 * nothing):
 *
 *     const dndA11y = useDndA11y();
 *     <DndContext accessibility={dndA11y} sensors={sensors} onDragEnd={...}>
 *
 * Every context in the tree must use this hook — a context without it goes
 * back to English defaults silently, which the static wiring test
 * (`dndA11y.wired.test.tsx`) guards.
 */
export function useDndA11y(): {
  announcements: Announcements;
  screenReaderInstructions: ScreenReaderInstructions;
} {
  const { t } = useTranslation("common");

  return {
    screenReaderInstructions: {
      draggable: t("dnd.instructions"),
    },
    announcements: {
      onDragStart: ({ active }) => t("dnd.pickedUp", { id: dragLabel(active) }),
      onDragOver: ({ active, over }) =>
        over
          ? t("dnd.movedOver", { id: dragLabel(active), over: dragLabel(over) })
          : t("dnd.noLongerOver", { id: dragLabel(active) }),
      onDragEnd: ({ active, over }) =>
        over
          ? t("dnd.droppedOver", {
              id: dragLabel(active),
              over: dragLabel(over),
            })
          : t("dnd.dropped", { id: dragLabel(active) }),
      onDragCancel: ({ active }) =>
        t("dnd.cancelled", { id: dragLabel(active) }),
    },
  };
}

/**
 * The sensors every drag context in the tree starts from: the pointer for
 * the hand, the keyboard for everybody else. The screen-reader instruction
 * promises "press the space bar, move with the arrows" — without the
 * KeyboardSensor that sentence is a promise the app does not keep, in any
 * language.
 *
 * `sortable` asks the keyboard to move the item among its sortable siblings
 * (a reorder reads as one swap, not a stream of coordinates); a plain
 * drag-into-target context keeps the library's default coordinates. The
 * wiring test reads every DndContext-owning file for this hook by name, so
 * a context that goes back to a pointer-only `useSensors` reddens the gate.
 */
export function useDndSensors(
  activationDistance: number,
  sortable: boolean,
): SensorDescriptor<SensorOptions>[] {
  return useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: activationDistance },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortable ? sortableKeyboardCoordinates : undefined,
      // The space bar picks up, as the instruction says. Enter is the
      // handle's own key: on a launcher tile the handle is a link, and a drag
      // that started on Enter swallowed the key that opens it.
      keyboardCodes: {
        start: [KeyboardCode.Space],
        cancel: [KeyboardCode.Esc],
        end: [KeyboardCode.Space, KeyboardCode.Enter, KeyboardCode.Tab],
      },
    }),
  );
}
