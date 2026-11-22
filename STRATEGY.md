# onesecondswe Strategy

## Vision

`onesecondswe` exists so that a software engineer sees a real opening within the hour it goes up and applies before the crowd.
It serves software engineers looking for work, early-career first, and it turns company career boards into one honest, filtered feed of openings.
It owns exactly one thing: a fresh, trustworthy list of real openings at companies worth applying to.

### The candidate is the only customer

The product is for the candidate, period.
There is no employer product: no paid listings, no sponsored placement, no reposts for sale, no boosted ranking.
Ranking is newest first, narrowed by what the candidate asked for, and never by who paid.
Data about candidates is never sold, and no B2B data product is built on it.
Success is the least time between a job going up and a candidate applying to it, not time spent on the site.
Money comes from the candidate, for speed: the board and a daily digest are free, and an instant alert for a high-confidence match is what a candidate pays for.
Browsing the board never needs an account; asking for a free account at the moment a candidate clicks through to apply is fine, and a paywall on the jobs themselves is not.

### Notifications earn their send

A notification exists to tell a candidate about new jobs that match what they asked for, never to pull them back for screen time.
An email goes out only when enough new jobs clear a high match-confidence bar, and never just because a schedule says it is time.
Anything that acts for a candidate, such as applying on their behalf, acts only on a job that candidate approved, one job at a time.
The board never mass-applies, because flooding employers with applications makes every candidate easier to ignore.

### Every claim on screen is true

The date on a job is when the company posted it, taken from its own board when the board gives a real date, and otherwise when this board first saw it.
A date is set once and never refreshed, so a job that closes and comes back keeps its original date.
A date is never synthesized, and a bucket such as "30+ days ago" counts as no date.
A board that recycles old listings shows its own old dates, and that is accepted rather than guessing which of its jobs are new.
Fewer correct results beat a list that only looks complete.
A listing the system cannot vouch for is hidden or closed out, not shown as live.
Public copy says only what the product does today, so unverifiable claims, numbers that rot, and ambitions dressed as features do not ship.
A feature that does not exist yet is labelled as coming, and nothing is sold before it exists.

### Straight from the source, within the hour

Jobs come straight from company applicant-tracking systems and career pages, never from aggregators or reposts.
A company the board cannot read directly is left out rather than filled in from LinkedIn, Indeed, or any other aggregator.
A new posting reaches the board within the hour it goes up.
The public company list is curated, and a company joins it only after review, never automatically because it raised money or showed up in a feed.
A candidate may track any company privately, and that never changes what other candidates see.
Adding a job is cheap, and closing one requires proof, so an empty or truncated scrape never closes a board.
A job is labelled with the level it actually states, never inflated or guessed upward.

### Fix the cause, then delete the workaround

A bug is fixed at its root, and the workaround is deleted once the root fix lands.
Constraints are not loosened and errors are not swallowed just to make a crash go away.
The system notices and heals its own failures, and pages the owner only when a human has to act.
Every incident gets a written postmortem tied to its fix.

### Cheap to run, simple to use

Runtime work is deterministic and close to free: a model learns something once, and plain code repeats it.
Matching jobs to each candidate is where the product is headed, and the per-candidate model spend it needs is taken on deliberately, with a cap and a plan to make it cheap.
Every other dollar is spent only on purpose, with a named cap.
A control, number, or line of copy stays only if it helps a candidate decide where to apply.
One press does one thing.

### Scope

It serves software engineers and does them well before it serves anyone else; other roles wait until that is true.
It is not a recruiting tool, an applicant-tracking system, a social network, or a feed of every job on the internet.
Hiring-trend charts serve a candidate deciding where to apply, and the product is not sold as hiring observability until it shows insights beyond the job list.

A change aligns when it gets a candidate to a real, fresh, relevant opening faster, or makes what the board shows more true.
A change should be resisted when it adds engagement for its own sake, lets money shape what a candidate sees, shows data the system cannot vouch for, acts for a candidate without their approval, or adds runtime cost with no named cap.
