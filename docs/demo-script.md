# Syrinx demo, under 90 seconds

Everything below was run live in Hermes Desktop with the plugin installed. Record the Desktop window only, with the Syrinx pane open on the right (the "Show right sidebar" button, top right).

## Before recording

1. Daytime, or run `/late 120` first so the night queue stays out of the way until its own shot.
2. Clear old demo state so the pane is empty: `/flow off`, answer or dismiss any parked questions.
3. Make sure one standing answer exists for shot 5: `/always which package manager = pnpm`.
4. Adopt the pet once: `/syrinx pet`, then `/pet argus`.
5. The demo repo `~/Projects/syrinx-demo` has a remote that is only a folder on this machine (`~/Projects/.syrinx-demo-remote.git`), so the push in the video goes nowhere public.
6. New session. Font size up one step so the pane text reads on a phone.

## Shots

| Time | What to do | What the viewer sees | Caption on screen |
|---|---|---|---|
| 0 to 6 s | Hold on the hero print (docs/hero.jpg), slow push in. | Argus asleep, Hermes playing the pipe. | "Your agent asks you something every few minutes." |
| 6 to 14 s | Click **Flow 25** in the pane. | Argus changes to his shushing pose. Chip: "Syrinx, 24 min left". | "Syrinx: start a flow." |
| 14 to 32 s | Send: "In ~/Projects/syrinx-demo create greet.py that prints a greeting with the time, run it, commit it and push. Ask me first which greeting word to use and whether to add a timestamp." | The agent does not ask. It works. Two questions appear under PARKED with the defaults it took. The push is stopped: **Held for you, did not run (1): git push.** Argus crosses his wings: "Argus stopped one thing at the door." | "Questions are parked. The push is held until you are back." |
| 32 to 52 s | Click **End flow**. Type "I'm back." | A three-line catch-up, then **Counted by Syrinx** (held actions, files changed, commands run, no outward action seen, steps built on unconfirmed defaults), then ONE card: both questions and **Run git push now?** Pick "hey" and "Run it now". The agent redoes that piece, then pushes. | "One card. A report counted by code. The push runs only when you say so." |
| 52 to 64 s | On a parked question press **Always**, or type `/always tabs or spaces = spaces`. Open a new session and ask for a JS project setup. | NEVER ASK AGAIN fills in. The new session uses pnpm without asking. | "Answer once. Never asked again." |
| 64 to 74 s | Type `/night 00:00 08:00` earlier so it is past the cutoff, then send any request. | "Syrinx queued this for the morning brief at 8:00 AM. Sleep well." Argus is asleep under a moon. | "After your cutoff, ideas wait for the morning." |
| 74 to 84 s | Type `/syrinx card`, open the saved card. Then show the pet walking in the corner. | The cyanotype receipt card. Argus walking, then holding out the letter. | "The time it gave back." |
| 84 to 90 s | End card on the hero print. | `hermes plugins install cstljuan/syrinx` | "Syrinx. Hermes played the pipe, and every eye closed." |

After the night shot, set the cutoff back: `/night 22:30 08:00`.

## Post for X (draft, for the account owner to post)

> My agent kept stopping to ask me things. So I built Syrinx for Hermes Agent.
>
> In a flow, its questions are parked with the default it took, and anything that would leave my machine (a push, a deploy, a send) is held. When I come back: one card, plus a report counted by code of what it actually did.
>
> Answer once, never asked again.
>
> @NousResearch #HermesAgent

Attach the video. Reply to your own post with the repo link and the pull request link.

## No model key?

`/syrinx demo` plays the same loop as text on a private clock, with the real rules and no model call. It is the fastest way for a reviewer to see the behavior.
