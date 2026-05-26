import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsInt, IsISO8601, IsOptional, Max, Min } from 'class-validator';

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
