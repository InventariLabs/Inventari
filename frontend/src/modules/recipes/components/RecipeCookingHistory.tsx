import { extractApiError } from "@/lib/errors";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Loader2, Star, FileText } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { CollapsibleDetailSection } from "./CollapsibleDetailSection";
import { Textarea } from "@/components/ui/Textarea";
import { useRecipeHistory, usePatchCookingHistory } from "../hooks/useRecipes";
import { formatDateMedium } from "@/utils/helpers";
import { useModules } from "@/contexts/ModulesContext";

interface RecipeCookingHistoryProps {
  recipeId: string;
}

// The backend stores the audit-document id in session notes as
// "document: <uuid>" — surface it as a link, not raw text.
const DOCUMENT_LINK_RE = /^document:\s*([0-9a-f-]{36})$/m;

function extractDocumentId(notes: string | null | undefined): string | null {
  if (!notes) return null;
  const match = notes.match(DOCUMENT_LINK_RE);
  return match ? match[1] : null;
}

function cleanNotes(notes: string | null | undefined): string | null {
  if (!notes) return null;
  return notes.replace(DOCUMENT_LINK_RE, "").trim() || null;
}

export default function RecipeCookingHistory({
  recipeId,
}: RecipeCookingHistoryProps) {
  const { t } = useTranslation(["recipes", "common"]);
  // The audit document lives in the warehouse module; where that module is off
  // (a focused module, an organization without it) the link would land on a
  // "module not enabled" page, so it is not offered.
  const { isModuleEnabled } = useModules();
  const documentsEnabled = isModuleEnabled("warehouse");
  const [showHistory, setShowHistory] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [sessionNotes, setSessionNotes] = useState("");
  const [sessionRating, setSessionRating] = useState<number>(0);

  const historyQuery = useRecipeHistory(showHistory ? recipeId : undefined);
  const patchHistoryMutation = usePatchCookingHistory(recipeId);

  const startEditSession = (session: {
    session_id: string;
    notes?: string | null;
    rating?: number | null;
  }) => {
    setEditingSessionId(session.session_id);
    setSessionNotes(cleanNotes(session.notes) ?? "");
    setSessionRating(session.rating ?? 0);
  };

  const saveSessionEdit = async () => {
    if (!editingSessionId) return;
    const historySession = historyQuery.data?.find(
      (s) => s.session_id === editingSessionId,
    );
    try {
      // Keep the audit-document link when saving user notes
      const documentId = historySession
        ? extractDocumentId(historySession.notes)
        : null;
      const notes = sessionNotes.trim();
      await patchHistoryMutation.mutateAsync({
        sessionId: editingSessionId,
        data: {
          notes:
            notes || documentId
              ? documentId
                ? `${notes}\ndocument: ${documentId}`
                : notes || null
              : null,
          rating: sessionRating || null,
        },
      });
      setEditingSessionId(null);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.history_failed")));
    }
  };

  return (
    <CollapsibleDetailSection
      title={t("history.title")}
      open={showHistory}
      onToggle={() => setShowHistory((v) => !v)}
    >
      <div className="space-y-3">
        {historyQuery.isLoading && (
          <div className="py-3 flex justify-center">
            <Loader2 size={18} className="animate-spin text-on-muted" />
          </div>
        )}
        {historyQuery.data?.length === 0 && (
          <p className="text-sm text-on-muted py-2">{t("history.empty")}</p>
        )}
        {historyQuery.data?.map((session) => (
          <div
            key={session.session_id}
            className="border border-border rounded-xl p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <div>
                <span className="text-xs text-on-secondary">
                  {session.cooked_at
                    ? formatDateMedium(session.cooked_at)
                    : "—"}
                </span>
                <span className="ml-2 text-xs text-on-muted">
                  {t("recipe.servings", { count: session.servings })}
                </span>
                {session.items_picked === 0 || session.items_total === 0 ? (
                  <span className="ml-2 text-xs font-medium text-on-muted">
                    {t("history.no_items_picked")}
                  </span>
                ) : (
                  <span className="ml-2 text-xs text-on-muted">
                    {t("history.items_picked", {
                      picked: session.items_picked,
                      total: session.items_total,
                    })}
                  </span>
                )}
                {session.duration_minutes != null &&
                  session.duration_minutes > 0 && (
                    <span className="ml-2 text-xs text-on-muted">
                      {t("history.duration_minutes", {
                        count: session.duration_minutes,
                      })}
                    </span>
                  )}
              </div>{" "}
              <Button
                onClick={() => startEditSession(session)}
                variant="link"
                size="contentSm"
                className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 px-0"
              >
                {t("history.edit")}
              </Button>
            </div>

            {editingSessionId === session.session_id ? (
              <div className="mt-2 space-y-2">
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <Button
                      key={star}
                      variant="ghost"
                      size="inline"
                      onClick={() => setSessionRating(star)}
                      aria-label={t("cooking.rateSession", { count: star })}
                      className="p-0.5"
                    >
                      <Star
                        size={16}
                        className={
                          star <= sessionRating
                            ? "text-amber-400 fill-amber-400"
                            : "text-on-muted"
                        }
                      />
                    </Button>
                  ))}
                </div>
                <Textarea
                  aria-label={t("history.notes_placeholder")}
                  value={sessionNotes}
                  onChange={(e) => setSessionNotes(e.target.value)}
                  rows={2}
                  placeholder={t("history.notes_placeholder")}
                  className="w-full text-sm border border-border rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-primary-300"
                />
                <div className="flex gap-2">
                  <Button
                    onClick={saveSessionEdit}
                    disabled={patchHistoryMutation.isPending}
                    variant="default"
                    size="contentSm"
                    className="py-1.5"
                  >
                    {patchHistoryMutation.isPending ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      t("common:form.save")
                    )}
                  </Button>
                  <Button
                    onClick={() => setEditingSessionId(null)}
                    variant="ghost"
                    size="contentSm"
                    className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 px-0 hover:bg-transparent"
                  >
                    {t("common:form.cancel")}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                {session.rating != null && (
                  <div className="flex gap-0.5 mt-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <Star
                        key={star}
                        size={13}
                        className={
                          star <= session.rating!
                            ? "text-amber-400 fill-amber-400"
                            : "text-on-muted"
                        }
                      />
                    ))}
                  </div>
                )}
                {documentsEnabled && extractDocumentId(session.notes) && (
                  <Link
                    to={`/warehouse/documents/${extractDocumentId(session.notes)}`}
                    className="inline-flex items-center gap-1 text-xs text-primary-600 hover:underline mt-1"
                  >
                    <FileText size={12} />
                    {t("history.document_link")}
                  </Link>
                )}
                {cleanNotes(session.notes) && (
                  <p className="text-sm text-on-secondary mt-1">
                    {cleanNotes(session.notes)}
                  </p>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </CollapsibleDetailSection>
  );
}
