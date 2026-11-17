// SPDX-License-Identifier: AGPL-3.0-or-later
import { Citation } from "../api";
import type { OpenPage } from "../pages/CaseView";

export default function CiteLinks({
  citations,
  openPage,
}: {
  citations: Citation[];
  openPage: OpenPage;
}) {
  return (
    <span className="cites">
      {citations.map((c, i) => (
        <button
          key={i}
          className="cite"
          title={`${c.doc_title ? c.doc_title + ": " : ""}„${c.quote}“`}
          onClick={() => openPage(c.global_seq, c.bbox)}
        >
          Bl. {c.global_seq}
        </button>
      ))}
    </span>
  );
}
