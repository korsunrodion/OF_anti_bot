import { ApiProperty } from '@nestjs/swagger';
import type { RiskLevel } from '../entities/tracking-link-input.entity';

const RISK_LEVELS = ['no risk', 'low', 'high', 'very high', 'extreme'] as const;

export class TrackingLinkSubscriptionDto {
  @ApiProperty({ example: 'link_abc123' })
  trackingLinkId: string;

  @ApiProperty({ example: 'john_doe' })
  username: string;

  @ApiProperty({ example: 987654 })
  userId: number;

  @ApiProperty({ example: '2024-03-15T10:00:00.000Z' })
  subscriptionDate: string;

  @ApiProperty({ enum: RISK_LEVELS, example: 'high' })
  riskLevel: RiskLevel;
}
