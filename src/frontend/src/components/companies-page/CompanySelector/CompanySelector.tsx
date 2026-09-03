import { Box, FormControl, InputLabel, Select, MenuItem, SelectChangeEvent } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { setSelectedATS, setSelectedCompanyId } from '../../../features/app/appSlice';
import { getCompanyById } from '../../../config/companies';
import { ATSConstants } from '../../../api/types';
import { selectEffectiveCompanies } from '../../../features/userCompanies/effectiveCompanies';
import { TextBadge } from '../../shared/TextBadge';

/**
 * Company selector dropdown
 *
 * Options come from `selectEffectiveCompanies`, which is the curated roster BY
 * REFERENCE unless the signed-in viewer owns custom boards — so for everyone
 * else this renders exactly what it always has.
 *
 * ONE ALPHABETICAL LIST. A user's own boards used to sit in a second block under
 * a "Your companies" subheader, below all ~135 curated ones. That put the
 * distinction ahead of the name: finding a company you track meant first
 * remembering which of the two lists it was filed under, and the second list was
 * off the bottom of a scrolling menu. Now every company is where its name says
 * it should be, and the ones you added carry a quiet badge — the distinction is
 * still there, it just stopped being the organising principle.
 */
export function CompanySelector() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const companies = useAppSelector(selectEffectiveCompanies);

  const handleCompanyChange = (event: SelectChangeEvent) => {
    const newCompanyId = event.target.value;
    dispatch(setSelectedCompanyId(newCompanyId));
    // `state.app.selectedATS` has no reader anywhere in the app. Left exactly as
    // it was rather than given a made-up value for a custom board — there is no
    // ATS to name, and nothing would read it if there were.
    dispatch(setSelectedATS(getCompanyById(newCompanyId)?.ats ?? ATSConstants.BackendScraper));
    // useCompanyLoader hook (in App.tsx) handles loading jobs automatically
  };

  return (
    <FormControl sx={{ minWidth: 200 }}>
      <InputLabel id="company-selector-label">Company</InputLabel>
      <Select
        labelId="company-selector-label"
        id="company-selector"
        value={selectedCompanyId}
        label="Company"
        onChange={handleCompanyChange}
      >
        {companies.map((company) => (
          <MenuItem key={company.id} value={company.id}>
            {/* The badge is a SIBLING of the name inside the row, not part of the
                name string, so the row's `value` stays the id and the rendered
                selection keeps reading as just the company. `justifyContent`
                pushes it to the right edge, where a column of badges is scannable
                instead of ragged. */}
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 1,
                width: '100%',
              }}
            >
              {company.name}
              {company.isCustom ? <TextBadge label="Custom" fontSize={9} /> : null}
            </Box>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
