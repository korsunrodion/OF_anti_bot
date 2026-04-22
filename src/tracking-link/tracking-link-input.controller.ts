import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { UpsertTrackingLinkDto } from './dto/upsert-tracking-link.dto';
import { TrackingLinkRepository } from './repositories/tracking-link.repository';
import {
  ApiBearerAuth,
  ApiBody,
  ApiOperation,
  ApiResponse,
  ApiTags,
} from '@nestjs/swagger';

@ApiBearerAuth()
@ApiTags('tracking-links/input')
@Controller('tracking-links/input')
export class TrackingLinkInputController {
  constructor(private readonly repository: TrackingLinkRepository) {}

  @ApiOperation({ summary: 'Upsert tracking link' })
  @ApiBody({ type: UpsertTrackingLinkDto })
  @ApiResponse({ status: 201, description: 'Tracking link upserted' })
  @Post()
  @HttpCode(201)
  async upsert(@Body() dto: UpsertTrackingLinkDto): Promise<void> {
    await this.repository.upsert(dto);
  }
}
