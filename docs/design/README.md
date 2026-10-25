# Design reference

Static mock-ups of every screen, exported from the design canvas "MOTIE ETLS Facility Letter Screens".
Open any file in a browser to see the screen (the support.js line can be ignored; the layout is plain HTML and inline CSS).

Use them as the visual reference for the Next.js frontend: layout, wording, colours, spacing and component patterns.
They are not code to copy: all data in them is made up, and names in [BRACKETS] are placeholders.
docs/SCREENS.md is the spec; where a mock-up and SCREENS.md disagree, SCREENS.md wins.

Palette: navy #13283A, green #2F7A55, cream #F7F5EF, white #FFFFFF, border #D9D6CC, muted text #4A5568,
info blue #1F5F8B / #E3EEF7, warning #7A4A00 / #FFF4E0. Fonts: IBM Plex Sans (UI), Source Serif 4 (headings, letter).
Touch targets at least 44px. Disabled actions always say why.

Screen files: Main (applicant home), Apply (facility letter form), Track (phone status), ApplyApproval, ApprovalStatus,
RequestCO, Records, RecordsOutgoing, Desk, PS, Absences, Minute, Assign, Review, NAC, Ecowas, CODesk, COCertify.
