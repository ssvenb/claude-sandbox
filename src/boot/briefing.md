## Tests

Every feature and function you add or change must be covered by unit tests, and so must every
bug you find: a test that fails without the fix. The basic functionality must also be covered by
integration tests. A bug that unit tests cannot reach (it only shows when the parts run together)
must be covered by an integration test instead.

Fix bugs test first: write the test that reproduces the bug, run it and see it fail, and only
then fix the bug and see the test pass.
