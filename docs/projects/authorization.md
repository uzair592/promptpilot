# Project Authorization

Every project endpoint requires an authenticated user and calls the shared policy before accessing project data.

| Role   | Read | Edit metadata | Archive | Manage membership |
| ------ | ---: | ------------: | ------: | ----------------: |
| owner  |  yes |           yes |     yes | yes, future slice |
| editor |  yes |           yes |      no |                no |
| member |  yes |            no |      no |                no |

Membership must be active. Detail access hides both missing and inaccessible projects as `404 Project not found`. Client-side role checks are presentation only; server policy is authoritative. The owner membership is never demoted or removed by this slice.
