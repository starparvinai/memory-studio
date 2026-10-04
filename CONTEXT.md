# Memory Studio

Memory Studio turns photos from an Immich album into a reviewable personal print project.

## Language

**Project**:
A one-time request to make a specific print output from a source album, with its own draft and chosen photos.
_Avoid_: Ongoing feed

**Source album**:
The Immich album chosen as the photo pool for one project.
_Avoid_: Library, collection

**Month window**:
The interval from one monthly anniversary of a child's birth to the next, determined from photo capture dates. Month 1 starts on the birth date.
_Avoid_: Calendar month

**Slot**:
One position in a print project for a selected photo from a specific month window, with an optional caption and crop.
_Avoid_: Tile

**Candidate**:
A photo from the source album whose capture date places it in a slot's month window and which can be considered for that slot.
_Avoid_: Match

**Alternative**:
A candidate presented beside the current suggestion so the user can choose a different photo for a slot.
_Avoid_: Backup

**Draft**:
An editable set of suggested slot choices that the user can review before export.
_Avoid_: Final book

**Analysis image**:
A reduced version of a candidate used to assess its visual content and compare it with other candidates.
_Avoid_: Print source

**Print source**:
The full-resolution still image of a selected candidate used to produce a print output.
_Avoid_: Preview

**Live Photo**:
A still image with a linked short motion clip. The still is the candidate for a print slot; the linked clip remains associated with it for motion formats.
_Avoid_: Video-only asset
