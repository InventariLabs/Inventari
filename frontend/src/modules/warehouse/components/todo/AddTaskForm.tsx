import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import type { Member } from "@/modules/warehouse/components/todo/WorkItemRow";
import { useCreateCustomWorkItem } from "@/modules/warehouse/hooks/useWorkItems";

/** A job nobody would write a document for — "move the rack" — added to the
 * list by hand, with an optional day. On the list, who it is for is chosen on
 * its row, the way it is for every other task; where the form is given
 * `members` (the board) it asks for the person too. */
export function AddTaskForm({
  members,
  onCreated,
}: {
  members?: Member[];
  onCreated?: () => void;
} = {}) {
  const { t } = useTranslation("warehouse");
  const create = useCreateCustomWorkItem();
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [assigneeId, setAssigneeId] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    create.mutate(
      {
        title: trimmed,
        due_date: dueDate || null,
        ...(members && { assignee_id: assigneeId || null }),
      },
      {
        onSuccess: () => {
          setTitle("");
          setDueDate("");
          setAssigneeId("");
          onCreated?.();
        },
      },
    );
  };

  return (
    <Card className="p-3 sm:p-4">
      <form
        onSubmit={submit}
        className="flex flex-wrap items-end gap-3"
        aria-label={t("todo.addTask.title")}
      >
        <Input
          label={t("todo.addTask.label")}
          placeholder={t("todo.addTask.placeholder")}
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          wrapperClassName="flex-1 min-w-48"
        />
        {members && (
          <NativeSelect
            label={t("todo.addTask.person")}
            value={assigneeId}
            onChange={(e) => setAssigneeId(e.target.value)}
            wrapperClassName="w-full sm:w-44"
          >
            <option value="">{t("todo.unassigned")}</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
          </NativeSelect>
        )}
        <DateInput
          label={t("todo.addTask.due")}
          value={dueDate}
          onChange={setDueDate}
          wrapperClassName="w-full sm:w-44"
        />
        <Button
          type="submit"
          className="max-sm:w-full"
          leftIcon={<Plus size={16} />}
          disabled={!title.trim() || create.isPending}
        >
          {t("todo.addTask.submit")}
        </Button>
      </form>
    </Card>
  );
}
