import { X, ImageIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useTranslation } from "react-i18next";

interface EquipmentImageUploadProps {
  imageFile: File | null;
  currentImageUrl: string | null;
  deleteImageFlag: boolean;
  onImageFileSet: (file: File | null) => void;
  onDeleteImageFlagSet: (flag: boolean) => void;
}

export default function EquipmentImageUpload({
  imageFile,
  currentImageUrl,
  deleteImageFlag,
  onImageFileSet,
  onDeleteImageFlagSet,
}: EquipmentImageUploadProps) {
  const { t } = useTranslation("equipment");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {t("form.fields.image", "Image")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {(imageFile || currentImageUrl) && !deleteImageFlag ? (
          <div className="relative inline-block">
            <img
              src={
                imageFile
                  ? URL.createObjectURL(imageFile)
                  : (currentImageUrl ?? "")
              }
              alt={t("form.fields.image", "Image")}
              loading="lazy"
              className="h-32 w-auto rounded-lg object-cover"
            />
            <Button
              type="button"
              variant="ghost"
              size="iconSm"
              aria-label={t("form.removeImage")}
              onClick={() => {
                onImageFileSet(null);
                if (currentImageUrl) onDeleteImageFlagSet(true);
              }}
              className="absolute -top-2 -right-2 rounded-full bg-red-500 text-white hover:bg-red-600 shadow-sm"
            >
              <X size={12} />
            </Button>
          </div>
        ) : (
          <label className="flex flex-col items-center justify-center gap-2 p-6 border border-dashed border-border rounded-lg cursor-pointer hover:border-primary-400 transition-colors">
            <ImageIcon size={24} className="text-on-muted" />
            <span className="text-xs text-on-muted">
              {t("form.upload_image", "Click to upload image")}
            </span>
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0] ?? null;
                if (file) {
                  onImageFileSet(file);
                  onDeleteImageFlagSet(false);
                }
              }}
            />
          </label>
        )}
      </CardContent>
    </Card>
  );
}
