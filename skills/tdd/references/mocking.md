# Mocking boundaries

Mock at system boundaries only:

- external APIs such as payment, email, map, or analytics services
- time, randomness, and generated IDs
- filesystem or database boundaries when a real test instance is impractical

Do not mock:

- modules/classes/functions owned by the project
- private methods or internal collaborators
- call counts/order when observable behavior can be asserted instead

At a system boundary, inject the dependency rather than constructing it deep inside
the behavior under test. The test should replace one clear boundary interface, not
patch internals.

Prefer specific adapter methods over one generic fetcher. A mock for `getUser(id)` is
clear; a mock for `fetch(path, options)` with conditional behavior usually spreads
production routing logic into the test.
