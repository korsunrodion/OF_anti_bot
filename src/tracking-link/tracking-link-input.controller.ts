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

const UPSERT_EXAMPLE = {
  trackingLinkId: 12345,
  trackingLinkName: '@model_username',
  subscriptions: [
    {
      id: '12345',
      username: 'john_doe',
      userId: 987654,
      subscriptionDate: '2024-06-01T12:00:00.000Z',
      avatarUrl: 'https://cdn.example.com/avatar.jpg',
      header: 'https://cdn.example.com/header.jpg',
      isOnlineMatchesSubscription: true,
      isReadingMessages: false,
    },
  ],
};

@ApiBearerAuth()
@ApiTags('tracking-links/input')
@Controller('tracking-links/input')
export class TrackingLinkInputController {
  constructor(private readonly repository: TrackingLinkRepository) {}

  @ApiOperation({ summary: 'Upsert tracking link' })
  @ApiBody({
    type: UpsertTrackingLinkDto,
    examples: {
      default: { summary: 'Example payload', value: UPSERT_EXAMPLE },
    },
  })
  @ApiResponse({ status: 201, description: 'Tracking link upserted' })
  @Post()
  @HttpCode(201)
  async upsert(@Body() dto: UpsertTrackingLinkDto): Promise<void> {
    await this.repository.upsert(dto);
  }
}
