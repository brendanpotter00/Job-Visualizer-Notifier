import { Box, Stack, Typography } from '@mui/material';
import { CompanyLogo } from '../CompanyLogo/CompanyLogo.tsx';
import { getCompanyById } from '../../../config/companies.ts';
import { CUSTOM_COMPANIES_CONFIG } from '../../../config/customCompanies.ts';
import { RESPONSIVE } from '../../../config/responsive';
import { useAuth } from '../../../features/auth/useAuth';
import { useGetUserCompaniesQuery } from '../../../features/userCompanies/userCompaniesApi';

interface CompanyJobHeaderProps {
  /** `job.company` — a compile-time `COMPANY_IDS` member OR a `u-<base36>` runtime id. */
  companyId: string;
  /** Job title, rendered as the card's `<h3>` under the board name. */
  title: string;
  /** Square edge length for the logo tile, in pixels. */
  logoSize: number;
}

/**
 * The left half of a job card's header: brand tile + [board name, job title].
 *
 * Company ids come from two disjoint namespaces. First-party companies are in
 * the compile-time `COMPANIES` list; a board the signed-in user added themselves
 * is keyed by an opaque `u-<base36>` id that only exists at runtime, in
 * `GET /api/users/companies`. Resolving a `u-…` id against the static list is
 * what shipped the reported bug: the name fell through to the raw id, so the
 * card read "u-ajhs85a7y0" over the job title with a "U" initial tile beside it.
 *
 * The split into two components below is deliberate and is NOT a style choice.
 * The runtime lookup needs a Redux/RTK Query subscription; a hook would force
 * that subscription onto every card on the Recent Jobs and companies pages, all
 * of which resolve statically and none of which need it. Branching on component
 * type keeps first-party cards free of the store entirely — no per-card
 * `useSelector` on lists that mount hundreds of them, and no Redux Provider
 * requirement for anything that renders a first-party card.
 *
 * The flag is checked HERE rather than inside the query's `skip` for the same
 * reason plus one more: with `VITE_CUSTOM_COMPANIES_ENABLED` off this feature
 * does not exist, and the contract is that the app is then byte-for-byte what
 * shipped before it — which includes not mounting a store-connected component.
 */
export function CompanyJobHeader({ companyId, title, logoSize }: CompanyJobHeaderProps) {
  const staticName = getCompanyById(companyId)?.name;
  if (staticName === undefined && CUSTOM_COMPANIES_CONFIG.isEnabled) {
    return <UserCompanyJobHeader companyId={companyId} title={title} logoSize={logoSize} />;
  }
  return (
    <HeaderRow
      companyId={companyId}
      name={staticName}
      hasBrandArt={staticName !== undefined}
      title={title}
      logoSize={logoSize}
    />
  );
}

/**
 * Name resolution for a board the user added themselves.
 *
 * Reads the name off the same `GET /api/users/companies` cache the My Companies
 * list already subscribes to, so arriving from that list costs no extra request
 * and a deep link/refresh costs exactly one (RTK Query dedupes it across every
 * card on the page).
 *
 * Only ever mounted with the custom-companies flag on (see above), and the query
 * additionally waits for sign-in: user companies are owner-scoped, so without
 * that check a card whose id resolves nowhere — a company dropped from
 * `companies.ts` while its jobs are still in the database — would fire an
 * authenticated request on the public Recent Jobs page and 401 for every
 * signed-out visitor.
 */
function UserCompanyJobHeader({ companyId, title, logoSize }: CompanyJobHeaderProps) {
  const { isAuthenticated } = useAuth();
  const { data: userCompanies } = useGetUserCompaniesQuery(undefined, { skip: !isAuthenticated });
  const name = userCompanies?.find((company) => company.id === companyId)?.displayName;
  return (
    <HeaderRow
      companyId={companyId}
      name={name}
      hasBrandArt={false}
      title={title}
      logoSize={logoSize}
    />
  );
}

/**
 * `name` is undefined only while the lookup above has nothing to offer (cache
 * not yet filled, signed out, company since removed). The board line is then
 * dropped rather than filled with a placeholder: the raw id is meaningless to
 * the reader, and inventing a label would put a name on the card that exists
 * nowhere else in the product.
 *
 * `hasBrandArt` is false for every user-added board. Their names are hostnames
 * or board slugs, so an initials tile would read "W" for www.janestreet.com —
 * an arbitrary letter, which is the same defect as the "U" it replaced.
 */
function HeaderRow({
  companyId,
  name,
  hasBrandArt,
  title,
  logoSize,
}: CompanyJobHeaderProps & { name?: string; hasBrandArt: boolean }) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
      <CompanyLogo
        companyId={companyId}
        displayName={name}
        hasBrandArt={hasBrandArt}
        size={logoSize}
        decorative
      />
      <Box sx={{ minWidth: 0 }}>
        {name !== undefined && (
          <Typography variant="subtitle2" color="text.secondary" fontWeight="bold">
            {name}
          </Typography>
        )}
        <Typography variant="h6" component="h3" sx={{ fontSize: RESPONSIVE.fontSize.cardTitle }}>
          {title}
        </Typography>
      </Box>
    </Stack>
  );
}
