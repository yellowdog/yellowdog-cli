// Work Requirement spec exercising retryPolicy and failurePolicy.
//
// Every Task is a self-contained `bash -c '<command>'` invocation — no task
// data / data-client files required. Each task deterministically produces a
// chosen exit code so the policy branches below are provably exercised.
//
// Resubmission flow under test (failurePolicy destinations are evaluated
// in order; the first matching entry wins):
//
//   spot-attempt ──(ALLOCATION_LOST persists after retries)──> on-demand-fallback
//                └─(OOM kill, exit 137)─────────────────────> high-memory
//   on-demand-fallback ──(any non-permanent error exhausted)─> dead-letter
//   high-memory ───────(FAILED and exit 137)────────────────> dead-letter
//   dead-letter: terminal landing group (no resubmission)
//
// Coverage:
//   * retryErrors via `includes` (errorTypes + processExitCodes)   — spot-attempt
//   * retryErrors via `excludes` (retry all but one exit code)     — on-demand-fallback
//   * retry-on-any-error (retryPolicy with no retryErrors)         — high-memory
//   * maxRetries: 0 (policy defined but retries disabled)          — dead-letter
//   * ordered, multi-destination failurePolicy                     — spot-attempt
//   * catch-all destination (no resubmitErrors)                    — on-demand-fallback
//   * AND-within-one-selector (statusesAtFailure + processExitCodes) — high-memory
//
// NOTE: ALLOCATION_LOST is a platform preemption event and cannot be forced
// from a bash exit code. The ALLOCATION_LOST branches are real, but to
// observe them you need an actual spot preemption; the tasks below drive the
// exit-code branches (137 / 143 / 2 / 1), which are fully deterministic.

// --- Selection helpers -----------------------------------------------------
// A TaskErrorSelector matches when *every* field it specifies matches (AND).
// A Selection matches when at least one `includes` entry matches and no
// `excludes` entry matches.
local byErrorTypes(types) = { errorTypes: { includes: types } };
local byExitCodes(codes) = { processExitCodes: { includes: codes } };

// --- Task helper -----------------------------------------------------------
// A bash Task whose entire behaviour lives in `arguments`: bash runs the
// command string verbatim and returns the given exit code.
local bashTask(name, command) = {
  name: name,
  taskType: 'bash',
  arguments: ['-c', command],
};
// Print a message then exit with a specific code.
local exitWith(name, message, code) =
  bashTask(name, "echo '" + message + "'; exit " + code);

{
  // No Work Requirement `name` — let the CLI generate a unique one per submit.
  taskGroups: [

    // 1) SPOT attempt: retry preemptions a few times, then fall back by
    //    error type to different on-demand / high-memory capacity.
    {
      name: 'spot-attempt',
      taskTypes: ['bash'],
      instancePricingPreference: 'SPOT_ONLY',
      retryPolicy: {
        maxRetries: 3,
        // Only retry transient preemptions (ALLOCATION_LOST) and SIGTERM
        // (143). Real application failures skip retry and hit failurePolicy.
        retryErrors: {
          includes: [
            byErrorTypes(['ALLOCATION_LOST']),
            byExitCodes([143]),
          ],
        },
      },
      failurePolicy: {
        resubmissionDestinations: [
          // Continued preemption -> guaranteed on-demand capacity.
          {
            destinationTaskGroup: 'on-demand-fallback',
            resubmitErrors: { includes: [byErrorTypes(['ALLOCATION_LOST'])] },
          },
          // OOM kill (exit 137) -> larger-memory group.
          {
            destinationTaskGroup: 'high-memory',
            resubmitErrors: { includes: [byExitCodes([137])] },
          },
        ],
      },
      tasks: [
        // exit 137 (OOM): not in retryErrors, so no retry; failurePolicy
        // matches exit 137 -> resubmitted to 'high-memory'.
        exitWith('spot-oom', 'simulating OOM kill', '137'),
        // exit 143 (SIGTERM): in retryErrors, so retried up to 3 times;
        // no failurePolicy destination matches 143 -> terminal FAILED.
        exitWith('spot-sigterm', 'simulating SIGTERM', '143'),
        // exit 1: not in retryErrors and no failurePolicy match -> FAILED
        // immediately, with no retry and no resubmission.
        exitWith('spot-hard-fail', 'unhandled error', '1'),
        // exit 0: control — completes successfully on first attempt.
        exitWith('spot-success', 'all good', '0'),
      ],
    },

    // 2) ON-DEMAND fallback: retry (almost) anything, then dead-letter.
    {
      name: 'on-demand-fallback',
      taskTypes: ['bash'],
      // A resubmission destination: keep the group open so it does not finish
      // before tasks are resubmitted into it from other groups.
      finishIfAllTasksFinished: false,
      instancePricingPreference: 'ON_DEMAND_ONLY',
      retryPolicy: {
        maxRetries: 2,
        // Retry every error EXCEPT a deterministic config error (exit 2),
        // which will never succeed on retry. Demonstrates `excludes`.
        retryErrors: {
          excludes: [byExitCodes([2])],
        },
      },
      failurePolicy: {
        resubmissionDestinations: [
          // Catch-all: no resubmitErrors => matches any exhausted failure.
          { destinationTaskGroup: 'dead-letter' },
        ],
      },
      tasks: [
        // exit 2: excluded from retry -> no retry; catch-all failurePolicy
        // resubmits to 'dead-letter'.
        exitWith('ondemand-config-error', 'deterministic config error', '2'),
        // exit 1: not excluded, so retried twice; once exhausted the
        // catch-all failurePolicy resubmits to 'dead-letter'.
        exitWith('ondemand-transient', 'transient error', '1'),
        // exit 0: control — succeeds first time.
        exitWith('ondemand-success', 'all good', '0'),
      ],
    },

    // 3) HIGH-MEMORY: retry on any error; resubmit only confirmed OOMs.
    {
      name: 'high-memory',
      taskTypes: ['bash'],
      // A resubmission destination: keep the group open so it does not finish
      // before tasks are resubmitted into it from other groups.
      finishIfAllTasksFinished: false,
      ram: [16.0, 'none'],  // >= 16 GB, no upper limit
      retryPolicy: {
        // No retryErrors => any error is eligible for retry.
        maxRetries: 2,
      },
      failurePolicy: {
        resubmissionDestinations: [
          {
            destinationTaskGroup: 'dead-letter',
            // AND within one selector: FAILED status *and* OOM exit code.
            resubmitErrors: {
              includes: [
                {
                  statusesAtFailure: { includes: ['FAILED'] },
                  processExitCodes: { includes: [137] },
                },
              ],
            },
          },
        ],
      },
      tasks: [
        // exit 137: retried twice (retry-any), then failurePolicy matches
        // FAILED + exit 137 -> resubmitted to 'dead-letter'.
        exitWith('highmem-oom', 'still OOM even with more RAM', '137'),
        // exit 1: retried twice; resubmitErrors needs exit 137, so no match
        // -> terminal FAILED (retries exhausted, no resubmission).
        exitWith('highmem-other-fail', 'non-OOM failure', '1'),
        // exit 0: control — succeeds first time.
        exitWith('highmem-success', 'all good', '0'),
      ],
    },

    // 4) DEAD-LETTER: terminal landing group. Policy defined but retries
    //    disabled (maxRetries: 0) to show the "define-but-disable" form.
    {
      name: 'dead-letter',
      taskTypes: ['bash'],
      // A resubmission destination: keep the group open so it does not finish
      // before tasks are resubmitted into it from other groups.
      finishIfAllTasksFinished: false,
      retryPolicy: { maxRetries: 0 },
      tasks: [
        // exit 1: maxRetries 0 means no retry, and there is no failurePolicy
        // here -> terminal FAILED on the first attempt.
        exitWith('deadletter-fail', 'final failure, no retries', '1'),
        // exit 0: control — succeeds first time.
        exitWith('deadletter-success', 'all good', '0'),
      ],
    },
  ],
}
