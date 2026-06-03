import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Transform, Type } from 'class-transformer';
import {
  IsArray,
  IsEnum,
  IsInt,
  IsISO8601,
  IsOptional,
  Max,
  Min,
} from 'class-validator';
import type { RiskLevel } from '../entities/tracking-link-subscriber.entity';

export const RISK_LEVELS = [
  'no risk',
  'low',
  'high',
  'very high',
  'extreme',
] as const;

export class SubscriberFilterDto {
  @ApiPropertyOptional({
    description:
      'Return only rows created at or after this ISO 8601 timestamp.',
    example: '2026-05-01T00:00:00.000Z',
  })
  @IsOptional()
  @IsISO8601()
  createdSince?: string;

  @ApiPropertyOptional({
    description:
      'Return only rows updated at or after this ISO 8601 timestamp.',
    example: '2026-05-01T00:00:00.000Z',
  })
  @IsOptional()
  @IsISO8601()
  updatedSince?: string;

  @ApiPropertyOptional({
    description:
      'Return only rows whose risk_level matches one of these values. ' +
      'Pass multiple via comma-separated string (?riskLevel=high,extreme) ' +
      'or repeated query keys (?riskLevel=high&riskLevel=extreme). ' +
      'Rows with NULL risk_level (not yet scored by the predict job) are ' +
      'excluded whenever this filter is set; omit it to include them.',
    enum: RISK_LEVELS,
    isArray: true,
    example: ['high', 'extreme'],
  })
  @IsOptional()
  @Transform(({ value }): RiskLevel[] | undefined => {
    if (value === undefined || value === null) return undefined;
    if (Array.isArray(value)) return value as RiskLevel[];
    if (typeof value === 'string')
      return value
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean) as RiskLevel[];
    return [value as RiskLevel];
  })
  @IsArray()
  @IsEnum(RISK_LEVELS, { each: true })
  riskLevel?: RiskLevel[];
}

export class PaginationQueryDto extends SubscriberFilterDto {
  @ApiPropertyOptional({ example: 1, minimum: 1, default: 1 })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  page: number = 1;

  @ApiPropertyOptional({ example: 20, minimum: 1, maximum: 1000, default: 20 })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(1000)
  limit: number = 20;
}

export class PaginatedResponseDto<T> {
  @ApiProperty({ isArray: true })
  data: T[];

  @ApiProperty({ example: 100 })
  total: number;

  @ApiProperty({ example: 1 })
  page: number;

  @ApiProperty({ example: 20 })
  limit: number;
}
