import { useMemo } from 'react';
import {
  FormControl,
  InputLabel,
  ListSubheader,
  Select,
  MenuItem,
  SelectChangeEvent,
} from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { setSelectedATS, setSelectedCompanyId } from '../../../features/app/appSlice';
import { getCompanyById } from '../../../config/companies';
import { ATSConstants } from '../../../api/types';
import { selectEffectiveCompanies } from '../../../features/userCompanies/effectiveCompanies';

/** Group heading shown only when the viewer actually has boards of their own. */
const CUSTOM_GROUP_LABEL = 'Your companies';
const PUBLIC_GROUP_LABEL = 'Tracked by us';

/**
 * Company selector dropdown
 *
 * Options come from `selectEffectiveCompanies`, which is the curated roster BY
 * REFERENCE unless the signed-in viewer owns custom boards — so for everyone
 * else this renders exactly what it always has.
 */
export function CompanySelector() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const companies = useAppSelector(selectEffectiveCompanies);

  const [publicCompanies, customCompanies] = useMemo(
    () => [companies.filter((c) => !c.isCustom), companies.filter((c) => c.isCustom)],
    [companies]
  );

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
        {/* Headings appear only when there are two groups to tell apart; with no
            custom boards the list is the flat one it has always been. */}
        {customCompanies.length > 0 && (
          <ListSubheader key="public-group">{PUBLIC_GROUP_LABEL}</ListSubheader>
        )}
        {publicCompanies.map((company) => (
          <MenuItem key={company.id} value={company.id}>
            {company.name}
          </MenuItem>
        ))}
        {customCompanies.length > 0 && (
          <ListSubheader key="custom-group">{CUSTOM_GROUP_LABEL}</ListSubheader>
        )}
        {customCompanies.map((company) => (
          <MenuItem key={company.id} value={company.id}>
            {company.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
