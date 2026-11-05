import type { FacilityLetter } from "@/lib/types";

/** The applicant's copy of the signed letter (SCREENS.md S3), once the Ministry has sent GRA's. */
export function LetterCopy({ letter }: { letter: FacilityLetter | null }) {
  if (!letter?.letter_copy_url) return null;
  return (
    <div className="notice notice-done small">
      <a href={`/files${letter.letter_copy_url}`} className="strong">
        Download your copy of the facility letter (PDF)
      </a>
      {/* [CONFIRM] How the importer collects a paper copy, if they need one. */}
      <span>The Ministry has sent the letter to GRA. This is your copy.</span>
    </div>
  );
}
