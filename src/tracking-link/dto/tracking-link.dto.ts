import { ApiProperty } from '@nestjs/swagger';
import type { RiskLevel } from '../entities/tracking-link-input.entity';

const RISK_LEVELS = ['no risk', 'low', 'high', 'very high', 'extreme'] as const;

export class TrackingLinkDto {
  @ApiProperty({ example: 'link_abc123' })
  trackingLinkId: string;

  @ApiProperty({ enum: RISK_LEVELS, example: 'high' })
  riskLevel: RiskLevel;

  @ApiProperty({ example: 42 })
  count: number;
}
