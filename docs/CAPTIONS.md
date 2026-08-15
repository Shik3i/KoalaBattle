# Captions

Captions are derived directly from public commentary and do not require speech. Whitespace is
normalized, text is bounded by the profile, and escaped by Svelte rendering. Segmentation uses
words and sentence boundaries with profile-specific line limits. Segment durations are
contiguous and proportional to visible character count.

Before synthesis, timing uses a deterministic speech-duration estimate. After a valid cached
WAV exists, all segments are regenerated against its actual duration. There is no fabricated
provider word-alignment claim.

`CaptionOverlay.svelte` is shared by replay, watch, and match OBS views. Landscape captions use
the lower 16:9 safe area; vertical captions use a higher, narrower 9:16 safe area. `aria-live`
and atomic updates provide a text alternative even with master audio muted.
