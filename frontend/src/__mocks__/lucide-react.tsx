import React from "react";

interface LucideIconProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string;
}

const MockIcon = React.forwardRef<SVGSVGElement, LucideIconProps>(
  ({ size = 24, className = "", "aria-label": ariaLabel, ...props }, ref) => (
    <svg
      ref={ref}
      width={size}
      height={size}
      className={className}
      aria-label={ariaLabel}
      {...props}
    >
      <rect width={size} height={size} />
    </svg>
  ),
);

MockIcon.displayName = "MockIcon";

// Explicit exports for icons used in the app to satisfy Vitest/TS
export const Home = MockIcon;
export const Package = MockIcon;
export const ShoppingBag = MockIcon;
export const ShoppingCart = MockIcon;
export const Camera = MockIcon;
export const BarChart3 = MockIcon;
export const ClipboardCheck = MockIcon;
export const Settings = MockIcon;
export const LogOut = MockIcon;
export const Menu = MockIcon;
export const X = MockIcon;
export const QrCode = MockIcon;
export const Plus = MockIcon;
export const Trash2 = MockIcon;
export const Calendar = MockIcon;
export const Tag = MockIcon;
export const AlertTriangle = MockIcon;
export const TrendingDown = MockIcon;
export const Edit2 = MockIcon;
export const Edit = MockIcon;
export const Search = MockIcon;
export const Filter = MockIcon;
export const ChevronDown = MockIcon;
export const ChevronLeft = MockIcon;
export const ChevronRight = MockIcon;
export const ArrowLeft = MockIcon;
export const Upload = MockIcon;
export const RefreshCw = MockIcon;
export const CheckCircle = MockIcon;
export const CheckCircle2 = MockIcon;
export const ArrowRight = MockIcon;
export const MapPin = MockIcon;
export const Building2 = MockIcon;
export const Loader2 = MockIcon;
export const Snowflake = MockIcon;
export const Refrigerator = MockIcon;
export const Archive = MockIcon;
export const ThermometerSnowflake = MockIcon;
export const FileText = MockIcon;
export const FileSearch = MockIcon;
export const Check = MockIcon;
export const MinusCircle = MockIcon;
export const Minus = MockIcon;
export const Move = MockIcon;
export const Eye = MockIcon;
export const Save = MockIcon;
export const Globe = MockIcon;
export const ShieldCheck = MockIcon;
export const Ruler = MockIcon;
export const Brain = MockIcon;
export const Square = MockIcon;
export const CheckSquare = MockIcon;
export const Download = MockIcon;
export const Clock = MockIcon;
export const History = MockIcon;
export const DollarSign = MockIcon;
export const XCircle = MockIcon;
export const Sparkles = MockIcon;
export const AlertCircle = MockIcon;
export const PiggyBank = MockIcon;
export const Circle = MockIcon;
export const LayoutGrid = MockIcon;
export const BarChart = MockIcon;
export const PieChart = MockIcon;
export const TrendingUp = MockIcon;
export const List = MockIcon;
export const Info = MockIcon;
export const ChevronUp = MockIcon;
export const MoreVertical = MockIcon;
export const MoreHorizontal = MockIcon;
export const Copy = MockIcon;
export const Printer = MockIcon;
export const Share2 = MockIcon;
export const User = MockIcon;
export const Users = MockIcon;
export const LogIn = MockIcon;
export const UserPlus = MockIcon;
export const Mail = MockIcon;
export const Lock = MockIcon;
export const Shield = MockIcon;
export const Bell = MockIcon;
export const BellOff = MockIcon;
export const Star = MockIcon;
export const Heart = MockIcon;
export const DownloadCloud = MockIcon;
export const ExternalLink = MockIcon;
export const Box = MockIcon;
export const Layers = MockIcon;
export const Database = MockIcon;
export const Smartphone = MockIcon;
export const Tablet = MockIcon;
export const Monitor = MockIcon;
export const CreditCard = MockIcon;
export const Wallet = MockIcon;
export const Map = MockIcon;
export const Pin = MockIcon;
export const Hash = MockIcon;
export const Fingerprint = MockIcon;
export const Key = MockIcon;
export const EyeOff = MockIcon;
export const Scan = MockIcon;
export const Barcode = MockIcon;
export const Repeat = MockIcon;
export const RotateCw = MockIcon;
export const RotateCcw = MockIcon;
export const HelpCircle = MockIcon;
export const FileDown = MockIcon; // Added this one specifically as it was missing
export const Plus2 = MockIcon;
export const Check2 = MockIcon;
export const X2 = MockIcon;
export const LogIn2 = MockIcon;
export const UserPlus2 = MockIcon;
export const Layout = MockIcon;
