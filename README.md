# DriveIQ

I got tired of seeing people get ripped off buying used cars. Sellers know the fair price. Buyers don't. That's the whole game.

This is my attempt to fix that with AI — four agents that together know more about your car's market value than most dealers do.

## What surprised me building this

The two-step chain (cheap extraction → quality reasoning) wasn't obvious upfront.
My first version used a single prompt for everything. It was slower, more expensive,
and the valuation quality was actually worse — the model kept getting distracted
mixing extraction logic with valuation reasoning in the same context window.

Treating prompts like code — single responsibility principle — made a real difference.

Also: storing prices as integers (paise, not rupees) saved me a floating-point
rounding bug I didn't even catch until I wrote the test. ₹6,20,000.00 ≠ ₹6,20,000.001.
