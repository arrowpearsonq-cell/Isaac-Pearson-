# clip-bot

Phone-only clipping: GitHub's free servers download, transcribe and edit; Claude runs it from chat.

1. **find** — top community clips (most viewed moments) from any Twitch streamers, with
   transcripts and preview frames. Inputs: streamers, range (24hr/7d/30d), per_streamer, match.
2. **render** — turns the chosen moments into 1080x1920 vertical clips: hook text, credit line,
   word-by-word captions, watermark. Also takes Twitch VOD, Kick or YouTube links with time ranges.

Finished clips are published as a GitHub release (public links) so Metricool can post them.
