# Stock Analysis Criteria

When analyzing each ticker, consider the following in addition to the tweet sentiment and fundamentals:

- **Upcoming earnings:** Flag if the company is likely reporting earnings within the next 30 days based on typical quarterly schedules.
- **Sector risk:** Note if the stock's sector faces current macro headwinds (tariffs, rate sensitivity, regulation).
- **Analyst consensus:** Highlight any disconnect between the Twitter sentiment and the analyst `recommendationKey`.
- **Valuation check:** If `trailingPE` or `forwardPE` is significantly above or below historical norms, mention it.
- **Momentum:** Compare `currentPrice` to `fiftyTwoWeekHigh` and `fiftyTwoWeekLow` to assess positioning.
- **Growth quality:** Use `earningsGrowth`, `revenueGrowth`, and `operatingMargins` to distinguish real growth from hype.
- **Balance sheet health:** Flag high `debtToEquity` as a risk factor.
- **Insider/institutional signals:** If mentioned in tweets or news, weight them more heavily.
