import { Camera } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

/**
 * Reading a product off a photo of its label.
 *
 * The module has no screens of its own — it enters other modules' flows: the
 * photo tab when a product is added, and the nutrition table scanner. So it
 * gets no launcher tile and no routes; it registers so that the build knows it
 * exists at all. Without this the store drew it in the default colour and the
 * registry answered "no such module" about something the backend offers, which
 * is a hard thing to tell apart from a module that failed to load.
 *
 * Where it is switched off, the screens that use it drop the photo tab rather
 * than offering a button whose request comes back refused.
 */
moduleRegistry.register({
  name: "vision",
  launcher: {
    displayName: "",
    icon: Camera,
    hidden: true,
  },
  routes: [],
});
