import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { ApiError } from "@/lib/api/client";
import { useSuggestGenome } from "@/lib/api/hooks";

interface SuggestGenomeFormProps {
  campaignId: string;
  allowedSlots: string[];
}

/**
 * "Suggest your own copy" form for the authed experiments page. Mirrors
 * the form at the bottom of `src/dashboard/templates/review.html`: a
 * slot dropdown restricted to the backend-provided allow-list, a copy
 * field (max 500 chars), an optional notes field, and a submit button.
 */
export function SuggestGenomeForm({
  campaignId,
  allowedSlots,
}: SuggestGenomeFormProps) {
  const suggest = useSuggestGenome(campaignId);

  const [slotName, setSlotName] = useState<string>(allowedSlots[0] ?? "");
  const [slotValue, setSlotValue] = useState("");
  const [description, setDescription] = useState("");
  const [flash, setFlash] = useState<
    | { kind: "success"; text: string }
    | { kind: "error"; text: string }
    | null
  >(null);

  if (allowedSlots.length === 0) {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFlash(null);

    const value = slotValue.trim();
    if (!value) {
      setFlash({ kind: "error", text: "Your copy cannot be empty." });
      return;
    }

    try {
      await suggest.mutateAsync({
        slot_name: slotName,
        slot_value: value,
        description: description.trim() || undefined,
      });
      setFlash({
        kind: "success",
        text: "Added to gene pool — it will be used next week.",
      });
      setSlotValue("");
      setDescription("");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? typeof err.detail === "object" &&
            err.detail !== null &&
            "detail" in (err.detail as Record<string, unknown>)
            ? String((err.detail as { detail: unknown }).detail)
            : err.message
          : "Something went wrong.";
      setFlash({ kind: "error", text: message });
    }
  }

  return (
    <div className="rounded-lg border border-[var(--border)] p-5">
      <h3 className="text-[15px] font-medium text-[var(--text)]">
        Suggest your own copy
      </h3>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        Add your own headline, subhead, or CTA to the gene pool. The next
        weekly generator will use it when proposing new variants.
      </p>

      <form
        className="mt-4 flex flex-col gap-3"
        onSubmit={(e) => void handleSubmit(e)}
      >
        <div>
          <Label htmlFor="suggest-slot">Slot</Label>
          <select
            id="suggest-slot"
            value={slotName}
            onChange={(e) => setSlotName(e.target.value)}
            className="h-10 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-3 text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            disabled={suggest.isPending}
          >
            {allowedSlots.map((slot) => (
              <option key={slot} value={slot}>
                {slot}
              </option>
            ))}
          </select>
        </div>

        <div>
          <Label htmlFor="suggest-value">Your copy</Label>
          <Input
            id="suggest-value"
            value={slotValue}
            onChange={(e) => setSlotValue(e.target.value)}
            maxLength={500}
            placeholder="e.g., Limited time: 40% off everything"
            disabled={suggest.isPending}
            required
          />
        </div>

        <div>
          <Label htmlFor="suggest-description">Notes (optional)</Label>
          <Input
            id="suggest-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            placeholder="What is this trying to do?"
            disabled={suggest.isPending}
          />
        </div>

        <div>
          <Button type="submit" size="sm" loading={suggest.isPending}>
            Add to gene pool
          </Button>
        </div>

        {flash ? (
          <p
            className={`text-xs ${
              flash.kind === "success"
                ? "text-[var(--green)]"
                : "text-[var(--red)]"
            }`}
            role="status"
          >
            {flash.text}
          </p>
        ) : null}
      </form>
    </div>
  );
}
