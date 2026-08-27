# Release Path Hardening — DR-3A (executed 2026-08-27)

Baseline: `eff7ce2aaf9300a287b20096a388ba91e4641557` (DR-2 approved)

## What was hardened (all API-verified, no Apple credentials)

1. **main-protection ruleset** (id 21632634, target branch, active)
   - block force push (`non_fast_forward`), block deletion (`deletion`)
   - require pull request before merge (`pull_request`, approval count = 0 —
     solo maintainer; not locking the repo with an impossible gate)
   - required status checks enforced via legacy branch protection
     (required_status_checks rule type is no longer accepted by the Ruleset
     API): `static checks`, `pytest (Python 3.10/3.11/3.12)`
2. **Legacy branch protection on main**: required status checks (4 real
   contexts), no force push, no deletions.
3. **Workflow-path protection**: GitHub Ruleset conditions only support
   `ref_name` — no path-specific ruleset at this GitHub tier. Honest
   limitation: `.github/workflows/**` is protected transitively by the
   main ruleset (any main change requires a PR + CI) — no fake path rule.
4. **Actions default permissions**: `default_workflow_permissions: read`
   (workflow-level read-back), `can_approve_pull_request_reviews: false`.
   Workflows with explicit `permissions:` are unaffected.
5. **desktop-release environment** (id via API): deployment branch policy =
   protected branches only; ZERO secrets. Reviewer gate: no team/app
   reviewer exists in this solo repository — attempted, unavailable;
   manual deployment gate = the human-triggered workflow_dispatch itself
   (self-review semantics, not independent-person approval — stated
   honestly).
6. **desktop-v-tag-protection ruleset** (id 21632678, target tag,
   `refs/tags/desktop-v*`): block deletion + block force update.
   Existing tags v1.0.0–v1.1.0 untouched (no ruleset applied).
7. **desktop-release.yml hardened**: workflow_dispatch only; required input
   = full 40-char commit SHA, mechanically asserted
   (checked-out == requested == GITHUB_SHA; no silent fallback to main);
   `environment: desktop-release`; `permissions: contents: read`;
   zero APPLE_* / secrets.* references; no publishing capability.

## Credential threat invariant (structural, secrets still 0)

- fork PR → ZERO Apple secret access (release workflow never runs on PRs)
- ordinary PR → ZERO (same)
- arbitrary branch push → ZERO (dispatch-only trigger)
- workflow file edit → requires PR + CI on protected main
- release workflow → protected environment + human dispatch

## Solo-maintainer honesty

This hardening protects against accidental/workflow compromise. It does NOT
provide true two-person control: if the sole GitHub owner account is fully
taken over, self-approval + environment gates do not constitute an
independent second reviewer. Not overstated.

## Verification record

- Ruleset API read-back: main-protection (deletion, non_fast_forward,
  pull_request) + desktop-v-tag-protection (deletion, non_fast_forward)
- Branch protection read-back: 4 status contexts present
- Actions read-back: default_workflow_permissions=read,
  can_approve_pull_request_reviews=false
- Environment read-back: desktop-release, branch_policy, secrets=0
- Test PR (temporary branch → PR → required CI → merge → branch deleted)
  proves the new engineering path works end-to-end
