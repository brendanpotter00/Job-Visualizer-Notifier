import { useMemo } from 'react';
import type { MouseEvent } from 'react';
import { Autocomplete, Box, TextField, createFilterOptions } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { setSelectedATS, setSelectedCompanyId } from '../../../features/app/appSlice';
import { getCompanyById } from '../../../config/companies';
import { ATSConstants } from '../../../api/types';
import { selectEffectiveCompanies } from '../../../features/userCompanies/effectiveCompanies';
import type { CompanyOption } from '../../../features/userCompanies/effectiveCompanies';
import { TextBadge } from '../../shared/TextBadge';

/**
 * Fixed field width. The old `<Select>` had `minWidth: 200` and grew to fit the
 * selected name; a text input can't size itself to its content, so it gets one
 * width instead. 240 keeps it close to the old 200 while leaving room for every
 * name on the roster but the very longest (which MUI ellipsizes). The parent
 * stacks the header into a column on phones, where `maxWidth: '100%'` stops it
 * overflowing a narrow screen.
 */
const FIELD_SX = { width: 240, maxWidth: '100%' } as const;

/**
 * Case-insensitive SUBSTRING match on the company name: typing "sar" finds
 * "Saronic", and so does "RONIC". These are MUI's defaults, spelled out because
 * they ARE the feature, not an incidental setting.
 */
const matchCompanyName = createFilterOptions<CompanyOption>({
  matchFrom: 'any',
  ignoreCase: true,
  stringify: (company) => company.name,
});

/**
 * The option the field shows for `state.app.selectedCompanyId`, found BY ID.
 *
 * The id can briefly match NO option: a custom board's `u-<id>` is selected
 * before `GET /api/users/companies` has landed, so the board isn't in the list
 * yet. `disableClearable` types `value` as non-null, so "nothing" can't be
 * `null`; it is a nameless stand-in instead. That renders an empty input with
 * the "Company" label resting inside it, which says "nothing picked yet" without
 * inventing a name. The stand-in is never added to `options`, so it can't show
 * up as a blank row or be picked; MUI 7 accepts a `value` outside `options`
 * without the "None of the options match" warning v5 printed. Once the list has
 * the id, the real option takes over.
 */
function resolveValue(
  companies: readonly CompanyOption[],
  selectedCompanyId: string
): CompanyOption {
  return (
    companies.find((company) => company.id === selectedCompanyId) ?? {
      id: selectedCompanyId,
      name: '',
      isCustom: false,
      sourceLabel: '',
    }
  );
}

/**
 * Company selector: a type-to-filter search over every company
 *
 * Options come from `selectEffectiveCompanies`, which is the curated roster BY
 * REFERENCE unless the signed-in viewer owns custom boards — so for everyone
 * else this renders exactly what it always has.
 *
 * A SEARCH, NOT A MENU. With ~250 companies, scrolling a menu to the one you
 * want is the slow part of using this page. Clicking or focusing the field still
 * opens the full alphabetical list, exactly like the old dropdown; typing
 * narrows it to the names containing what was typed. The field always holds a
 * company (`disableClearable`), because the page always shows one: typing and
 * then leaving without picking puts the selected name back (`clearOnBlur`).
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
  // Memoized so a stand-in keeps one identity across renders: MUI resets the
  // input text whenever `value` changes identity, which would wipe what the
  // user is typing on any unrelated re-render.
  const value = useMemo(
    () => resolveValue(companies, selectedCompanyId),
    [companies, selectedCompanyId]
  );

  const handleCompanyChange = (_event: unknown, company: CompanyOption) => {
    const newCompanyId = company.id;
    dispatch(setSelectedCompanyId(newCompanyId));
    // `state.app.selectedATS` has no reader anywhere in the app. Left exactly as
    // it was rather than given a made-up value for a custom board — there is no
    // ATS to name, and nothing would read it if there were.
    dispatch(setSelectedATS(getCompanyById(newCompanyId)?.ats ?? ATSConstants.BackendScraper));
    // useCompanyLoader hook (in App.tsx) handles loading jobs automatically
  };

  return (
    <Autocomplete
      id="company-selector"
      sx={FIELD_SX}
      options={companies}
      value={value}
      onChange={handleCompanyChange}
      getOptionLabel={(company) => company.name}
      getOptionKey={(company) => company.id}
      isOptionEqualToValue={(option, selected) => option.id === selected.id}
      filterOptions={matchCompanyName}
      disableClearable
      openOnFocus
      selectOnFocus
      clearOnBlur
      autoHighlight
      // On a phone, picking a company drops the keyboard so the page it just
      // switched to is visible. A mouse pick keeps focus where it was.
      blurOnSelect="touch"
      noOptionsText="No companies match"
      renderOption={(props, company) => {
        const { key, ...optionProps } = props;
        return (
          <li key={key} {...optionProps}>
            {/* The badge is a SIBLING of the name inside the row, not part of
                the option's label, so `getOptionLabel` (what the input shows
                and what typing matches against) stays just the company name.
                `justifyContent` pushes it to the right edge, where a column of
                badges is scannable instead of ragged. */}
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
          </li>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label="Company"
          slotProps={{
            htmlInput: {
              ...params.inputProps,
              // `selectOnFocus` selects the name only on the first click after
              // the field gains focus, and a mouse pick leaves focus in the
              // field. Without this, picking a second company straight after the
              // first types onto the end of the first's name ("Saronicanth") and
              // matches nothing. Only while the field still shows the selected
              // name: in a half-typed query a click should just move the caret.
              onClick: (event: MouseEvent<HTMLInputElement>) => {
                if (event.currentTarget.value === value.name) event.currentTarget.select();
              },
            },
          }}
        />
      )}
    />
  );
}
