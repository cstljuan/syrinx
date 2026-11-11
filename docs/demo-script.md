# Syrinx demo, under 90 seconds

Everything below was run live in Hermes Desktop with the plugin installed. Record the Desktop window only, with the Syrinx pane open on the right (the "Show right sidebar" button, top right).

## Before recording

1. Daytime, or run `/late 120` first so the night queue stays out of the way until its own shot.
2. Clear old demo state so the pane is empty: `/flow off`, answer or dismiss any parked questions.
3. Make sure one standing answer exists for shot 5: `/always which package manager = pnpm`.
4. Adopt the pet once: `/syrinx pet`, then `/pet argus`.
5. New session. Font size up one step so the pane text reads on a phone.

## Shots

| Time | What to do | What the viewer sees | Caption on screen |
|---|---|---|---|
| 0 to 6 s | Hold on the hero print (docs/hero.jpg), slow push in. | Argus asleep, Hermes playing the pipe. | "Your agent asks you something every few minutes." |
| 6 to 14 s | Click **Flow 25** in the pane. | Argus changes to his shushing pose. Chip: "Syrinx, 24 min left". | "Syrinx: start a flow." |
| 14 to 32 s | Send: "In /tmp/syrinx-demo create greet.py that prints a greeting with the time, run it, and ask me first which greeting word to use and whether to add a timestamp." | The agent does not ask. It works. Two questions appear under PARKED with the defaults it took. Argus crosses his wings. | "Questions are parked with the default taken. The work continues." |
| 32 to 52 s | Click **End flow**. Type "I'm back." | A three-line catch-up, then **Counted by Syrinx** (files changed, commands run, nothing left your machine, steps built on unconfirmed defaults), then ONE card with both questions. Pick "hey". The agent redoes that piece. | "One card. And a report counted by code, not written by the model." |
| 52 to 64 s | On a parked question press **Always**, or type `/always tabs or spaces = spaces`. Open a new session and ask for a JS project setup. | NEVER ASK AGAIN fills in. The new session uses pnpm without asking. | "Answer once. Never asked again." |
| 64 to 74 s | Type `/night 00:00 08:00` earlier so it is past the cutoff, then send any request. | "Syrinx queued this for the morning brief at 8:00 AM. Sleep well." Argus is asleep under a moon. | "After your cutoff, ideas wait for the morning." |
| 74 to 84 s | Type `/syrinx card`, open the saved card. Then show the pet walking in the corner. | The cyanotype receipt card. Argus walking, then holding out the letter. | "The time it gave back." |
| 84 to 90 s | End card on the hero print. | `hermes plugins install cstljuan/syrinx` | "Syrinx. Hermes played the pipe, and every eye closed." |

After the night shot, set the cutoff back: `/night 22:30 08:00`.

## Post for X (draft, for the account owner to post)

> My agent kept stopping to ask me things. So I built Syrinx for Hermes Agent.
>
> In a flow, its questions are parked with the default it took. When I come back: one card, plus a report counted by code of what it actually did.
>
> Answer once, never asked again.
>
> @NousResearch #HermesAgent

Attach the video. Reply to your own post with the repo link and the pull request link.

## No model key?

`/syrinx demo` plays the same loop as text on a private clock, with the real rules and no model call. It is the fastest way for a reviewer to see the behavior.
