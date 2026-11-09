# Kairos demo, under 90 seconds (draft for Juan to edit)

Format: 16:9 screen recording of the Hermes Desktop app with the Kairos pane open on the right and the Cerberus pet popped out at the bottom of the screen. Voice-over or on-screen captions, Juan's choice. No music until Juan approves any spend. Every shot shows the real plugin doing the real thing; nothing is staged in post.

| Time | On screen | Caption or line |
|---|---|---|
| 0 to 6 s | Juan's own editor on the left, Hermes on the right, the agent mid-task. Phone face up next to the keyboard. | "The agent works. I scroll." |
| 6 to 14 s | Type `/flow 45`. The chip turns accent blue: "Kairos · 45 min left". The pet's bubble: "Kairos · focus until 3:45 PM". | "Kairos: the agent waits for the right moment." |
| 14 to 30 s | Time-lapse. The agent hits a question; instead of a card, the pane shows it under Parked with "Default taken: Postgres". The chip reads "1 parked", then "2 parked". The phone stays face down. | "Questions get parked with the default it would have picked. It keeps working. Approvals still reach me." |
| 30 to 44 s | Block ends. Juan types one word. The agent replies with a three-line catch-up and one clarify card holding both parked questions, the defaults pre-marked. Juan picks one different answer; the agent redoes that piece. | "When I come back: three lines, one card, every question at once." |
| 44 to 62 s | Clock shows 10:41 PM. Juan types a new request. The reply is Kairos: "It is 10:41 PM. Your cutoff is 10:30 PM, so Kairos queued this for the morning brief at 8:00 AM. Sleep well." The pet's bubble: "Kairos · night until 8:00 AM". Cut to 8:02 AM: the agent greets him and starts the queued request on its own. | "After my cutoff it queues the work and tells me to sleep. In the morning it starts without being asked." |
| 62 to 76 s | `/kairos receipt`. The pane's Receipt section: focus kept 3 h 12 min, 14 questions parked, 3 batches, 2 late nights queued. | "The receipt: time it gave back." |
| 76 to 86 s | Title card in the Hermes look (navy, cream serif): Kairos, the Cerberus engraving, `hermes plugins install https://github.com/cstljuan/kairos`. | "Kairos. Chronos is clock time. Kairos is the right moment." |

## Recording checklist

- Hermes Desktop with the `kairos` plugin enabled for the profile, the pane docked right, the pet popped out.
- A real task with at least two natural questions (a scaffold with a database choice and a naming choice works).
- System clock: record the Night shot last, either after 10:30 PM for real or with the cutoff set to the current time with `/night HH:MM` (say so in the post if used).
- Capture at 1080p or above, 30 fps. Keep the cursor visible.
- Under 90 seconds total. Trim the time-lapse first if long.

## The X post (Juan edits and posts himself)

> My agent is fast. Kairos makes sure it waits for the right moment.
>
> A Hermes plugin that parks the agent's questions while I'm heads-down, hands them back in one card when I'm back, and after 10:30 PM queues my own requests for the morning and tells me to sleep.
>
> Built for the @NousResearch Hermes Agent Plugin Hackathon. Open source: github.com/cstljuan/kairos
