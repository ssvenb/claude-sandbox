## Tests

Every feature and function you add or change must be covered by unit tests. The basic
functionality must also be covered by integration tests.

Every bug you find must be covered by a regression test: a test that fails on the buggy code and
passes once the bug is fixed. Put it at the lowest level that reproduces the bug, which is a unit
test, or an integration test if the bug only shows when the parts run together.

Fix bugs test first (test-driven development, red-green-refactor):

1. Red: write the regression test and run it against the unfixed code. It must fail, and for the
   reason the bug gives. A test that passes on the broken code does not cover the bug, so
   tighten it until it fails.
2. Green: fix the bug, then run the test again and see it pass, along with the tests around it.
3. Refactor: clean up the fix and the test while the tests stay green.
