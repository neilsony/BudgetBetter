# Refresh runs on demand and on Paydays, not on webhooks

A Refresh happens when the owner clicks Refresh and confirms, or automatically at noon on a Payday. There is no Plaid webhook listener, because receiving webhooks needs a public HTTPS endpoint and this app only exists on a laptop.

The Payday job is a launchd agent that runs **every day** at noon and immediately exits unless the date is a Payday. A launchd interval cannot express "every second Friday", so the schedule lives in code (`is_payday`) where it is testable, and the plist only decides how often to ask.

## Consequences

Data is as fresh as the last Refresh, which is the intent: the owner wanted spending numbers that hold still between paydays rather than moving under them. The two-step confirmation on the button is deliberate friction for the same reason.
