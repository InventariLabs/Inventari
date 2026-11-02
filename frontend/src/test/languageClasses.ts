import {
  SUPPORTED_LANGUAGES,
  isCommunityLanguage,
  type Language,
} from "@/i18n/languages";

/** The languages every change must carry in full — what the gates require. */
export const MAINTAINED_LANGUAGES: Language[] = SUPPORTED_LANGUAGES.filter(
  (language) => !isCommunityLanguage(language),
);

/** The languages that may ship below full coverage. */
export const COMMUNITY_LANGUAGES: Language[] =
  SUPPORTED_LANGUAGES.filter(isCommunityLanguage);
